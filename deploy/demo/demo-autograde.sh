#!/usr/bin/env bash
# demo-autograde: status, upgrade, reset and logs for the AutoGrade demo console on the droplet.
set -euo pipefail

DEMO_DIR=${DEMO_DIR:-/opt/autograde-demo}
ERP_DIR=${ERP_DIR:-/opt/autoerp}
HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:${DEMO_PORT:-8100}/health}
HEALTH_TRIES=${HEALTH_TRIES:-30}
HEALTH_GAP=${HEALTH_GAP:-4}
MIN_FREE_GB=${MIN_FREE_GB:-8}

readonly IMAGE_REPO=ghcr.io/delta-anugrah/autograde
readonly CONTAINER=autograde_demo_console
readonly ERP_SITE=demo.smagri.id # never read from the environment: the other site on this stack is production
readonly ERP_DAYS=90
readonly CONSOLE_DAYS=365

usage() {
	cat <<'EOF'
Usage: demo-autograde <command>

  status            running version, health, memory and free disk
  upgrade vX.Y.Z    switch to vX.Y.Z-cpu, roll back if it does not come up healthy
  reset             fresh demo data on both sides: AutoERP demo first, then the console
  logs              follow the console log
EOF
}

say() { printf '%s\n' "$*"; }
die() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

env_file() { printf '%s/.env' "$DEMO_DIR"; }

require_env() { [ -f "$(env_file)" ] || die "$(env_file) not found"; }

env_get() { sed -n "s/^$1=//p" "$(env_file)" | tail -n 1; }

env_set() {
	local file tmp
	file=$(env_file)
	tmp=$(mktemp "$file.XXXXXX")
	awk -v key="$1" -v value="$2" '
		index($0, key "=") == 1 { print key "=" value; found = 1; next }
		{ print }
		END { if (!found) print key "=" value }
	' "$file" >"$tmp"
	chmod 600 "$tmp"
	mv "$tmp" "$file"
}

compose() { (cd "$DEMO_DIR" && docker compose "$@"); }

erp_compose() { docker compose -f "$ERP_DIR/docker-compose.prod.yml" "$@"; }

free_gb() { df -BG --output=avail / | tail -n 1 | tr -dc '0-9'; }

running_version() {
	curl -fsS --max-time 4 "$HEALTH_URL" 2>/dev/null | sed -n 's/.*"version":"\([^"]*\)".*/\1/p' || true
}

version_of() {
	local tag=${1##*:}
	printf '%s' "${tag%-cpu}"
}

wait_for_version() {
	local i
	for ((i = 0; i < HEALTH_TRIES; i++)); do
		[ "$(running_version)" = "$1" ] && return 0
		sleep "$HEALTH_GAP"
	done
	return 1
}

cmd_status() {
	require_env
	local version
	version=$(running_version)
	say "Image     : $(env_get PALMGRADE_AUTOGRADE_IMAGE)"
	say "Serving   : ${version:-not answering}"
	docker ps -a --filter "name=^${CONTAINER}\$" --format 'Container : {{.Status}}' || true
	docker stats --no-stream --format 'Memory    : {{.MemUsage}}' "$CONTAINER" 2>/dev/null || true
	say "Free disk : $(free_gb)G (upgrade needs ${MIN_FREE_GB}G)"
}

roll_back() {
	local old=$1 new=$2 version=$3
	[ -n "$old" ] || die "$version did not come up healthy. See: demo-autograde logs"
	say "$version did not come up healthy, rolling back to $(version_of "$old") ..."
	env_set PALMGRADE_AUTOGRADE_IMAGE "$old"
	compose up -d || true
	docker rmi "$new" >/dev/null 2>&1 || true
	wait_for_version "$(version_of "$old")" ||
		die "$version failed and $(version_of "$old") did not come back either. See: demo-autograde logs"
	die "$version failed; the demo is back on $(version_of "$old") and the failed image was removed."
}

cmd_upgrade() {
	local version=${1:-} old new free
	[[ $version =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must look like v1.20.0, got '$version'"
	require_env
	new="$IMAGE_REPO:$version-cpu"
	old=$(env_get PALMGRADE_AUTOGRADE_IMAGE)
	if [ "$old" = "$new" ]; then
		say "Already on $version."
		return 0
	fi
	free=$(free_gb)
	[ "${free:-0}" -ge "$MIN_FREE_GB" ] || die "only ${free}G free, need ${MIN_FREE_GB}G. Nothing downloaded."
	say "Downloading $new ..."
	docker pull "$new" || die "download failed. Nothing changed."
	env_set PALMGRADE_AUTOGRADE_IMAGE "$new"
	compose up -d || true
	wait_for_version "$version" || roll_back "$old" "$new" "$version"
	if [ -n "$old" ]; then docker rmi "$old" >/dev/null 2>&1 || true; fi
	say "OK: the demo runs $version."
}

cmd_reset() {
	say "1/2 AutoERP demo ($ERP_SITE), $ERP_DAYS days. This takes 20 to 40 minutes."
	erp_compose exec -T backend bench --site "$ERP_SITE" execute erpnext.palm_mill.demo.reset \
		--kwargs "{'days': $ERP_DAYS}" || die "AutoERP demo reset failed; the console was not touched."
	say "2/2 Console, $CONSOLE_DAYS days."
	compose exec -T console python scripts/seed-console-demo.py --hari "$CONSOLE_DAYS" --reset ||
		die "console reset failed."
	say "OK: both sides reset."
}

cmd_logs() { docker logs --tail 200 -f "$CONTAINER"; }

case "${1:-}" in
status) cmd_status ;;
upgrade) cmd_upgrade "${2:-}" ;;
reset) cmd_reset ;;
logs) cmd_logs ;;
help | -h | --help) usage ;;
*)
	usage >&2
	exit 1
	;;
esac
