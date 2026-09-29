#!/usr/bin/env bash
# Tests demo-autograde.sh with stub docker, curl and df on PATH: no Docker, no droplet.
#
#   bash deploy/demo/demo-autograde.test.sh

set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL %s\n       want: %s\n       got : %s\n' "$1" "$2" "$3"; }
eq() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "$2" "$3"; fi; }
has() { if grep -qF -- "$2" <<<"$3"; then ok "$1"; else bad "$1" "contains: $2" "$3"; fi; }
lacks() { if grep -qF -- "$2" <<<"$3"; then bad "$1" "lacks: $2" "$3"; else ok "$1"; fi; }
fails() { if [ "$2" -ne 0 ]; then ok "$1"; else bad "$1" "non-zero exit" "0"; fi; }

REPO=ghcr.io/delta-anugrah/autograde
OLD=$REPO:v1.19.0-cpu
NEW=$REPO:v1.20.0-cpu

setup() {
	ROOT=$(mktemp -d)
	BIN=$ROOT/bin
	DEMO=$ROOT/demo
	ERP=$ROOT/erp
	mkdir -p "$BIN" "$DEMO" "$ERP"
	: >"$DEMO/docker-compose.yml"
	: >"$ERP/docker-compose.prod.yml"
	printf 'PALMGRADE_AUTOGRADE_IMAGE=%s\nWEBHOOK_SECRET=keep-me\n' "$OLD" >"$DEMO/.env"
	chmod 600 "$DEMO/.env"
	echo 19 >"$ROOT/free"
	echo v1.19.0 >"$ROOT/health"
	: >"$ROOT/argv"

	# `up -d` makes /health report the version in .env, or go down when that version is broken.
	cat >"$BIN/docker" <<EOF
#!/usr/bin/env bash
echo "docker \$*" >>"$ROOT/argv"
case "\$*" in
  pull*) [ -e "$ROOT/pull_fails" ] && exit 1 ;;
  *"exec -T backend"*) [ -e "$ROOT/erp_fails" ] && exit 1 ;;
  *"up -d"*)
    img=\$(sed -n 's/^PALMGRADE_AUTOGRADE_IMAGE=//p' "$DEMO/.env")
    v=\${img##*:}; v=\${v%-cpu}
    if [ -e "$ROOT/broken" ] && [ "\$v" = v1.20.0 ]; then echo down >"$ROOT/health"; else echo "\$v" >"$ROOT/health"; fi ;;
esac
exit 0
EOF
	cat >"$BIN/curl" <<EOF
#!/usr/bin/env bash
v=\$(cat "$ROOT/health")
[ "\$v" = down ] && exit 7
echo '{"status":"ok","mode":"console","version":"'"\$v"'"}'
EOF
	cat >"$BIN/df" <<EOF
#!/usr/bin/env bash
echo "Avail"
echo " \$(cat "$ROOT/free")G"
EOF
	chmod +x "$BIN"/*
}
teardown() { rm -rf "$ROOT"; }
run() {
	PATH="$BIN:$PATH" DEMO_DIR="$DEMO" ERP_DIR="$ERP" HEALTH_TRIES=2 HEALTH_GAP=0 \
		bash "$HERE/demo-autograde.sh" "$@" 2>&1
}
image_in_env() { sed -n 's/^PALMGRADE_AUTOGRADE_IMAGE=//p' "$DEMO/.env"; }
argv() { cat "$ROOT/argv"; }

echo "upgrade: healthy new version"
setup
out=$(run upgrade v1.20.0); rc=$?
eq "exits 0" 0 "$rc"
eq ".env points at the new image" "$NEW" "$(image_in_env)"
has "pulls the cpu tag" "docker pull $NEW" "$(argv)"
has "removes the old image" "docker rmi $OLD" "$(argv)"
lacks "keeps the new image" "docker rmi $NEW" "$(argv)"
has "other settings survive" "WEBHOOK_SECRET=keep-me" "$(cat "$DEMO/.env")"
eq ".env stays owner-only" "-rw-------" "$(ls -l "$DEMO/.env" | cut -c1-10)"
teardown

echo "upgrade: unhealthy new version rolls back"
setup
touch "$ROOT/broken"
out=$(run upgrade v1.20.0); rc=$?
fails "exits non-zero" "$rc"
eq ".env back on the old image" "$OLD" "$(image_in_env)"
eq "old version is serving again" v1.19.0 "$(cat "$ROOT/health")"
has "removes the broken image" "docker rmi $NEW" "$(argv)"
lacks "keeps the old image" "docker rmi $OLD" "$(argv)"
has "says it rolled back" "v1.19.0" "$out"
teardown

echo "upgrade: refuses when the disk is low"
setup
echo 5 >"$ROOT/free"
out=$(run upgrade v1.20.0); rc=$?
fails "exits non-zero" "$rc"
lacks "downloads nothing" "docker pull" "$(argv)"
eq ".env untouched" "$OLD" "$(image_in_env)"
has "names the limit" "8G" "$out"
teardown

echo "upgrade: failed download changes nothing"
setup
touch "$ROOT/pull_fails"
out=$(run upgrade v1.20.0); rc=$?
fails "exits non-zero" "$rc"
eq ".env untouched" "$OLD" "$(image_in_env)"
lacks "does not restart" "up -d" "$(argv)"
teardown

echo "upgrade: rejects anything that is not vX.Y.Z"
for bad_version in "" "1.20.0" "v1.20" "latest" "v1.20.0-cpu" "v1.20.0;reboot"; do
	setup
	out=$(run upgrade "$bad_version"); rc=$?
	fails "rejects '$bad_version'" "$rc"
	eq "no docker call for '$bad_version'" "" "$(argv)"
	teardown
done

echo "upgrade: same version is a no-op"
setup
out=$(run upgrade v1.19.0); rc=$?
eq "exits 0" 0 "$rc"
eq "no docker call" "" "$(argv)"
teardown

echo "upgrade: first install from an empty .env"
setup
printf 'WEBHOOK_SECRET=keep-me\n' >"$DEMO/.env"
chmod 600 "$DEMO/.env"
out=$(run upgrade v1.20.0); rc=$?
eq "exits 0" 0 "$rc"
eq ".env gains the image" "$NEW" "$(image_in_env)"
lacks "removes nothing" "docker rmi" "$(argv)"
teardown

echo "reset: AutoERP demo first, then the console, on the demo site only"
setup
out=$(ERP_SITE=prod.example run reset); rc=$?
eq "exits 0" 0 "$rc"
has "resets the ERP demo for 90 days" "exec -T backend bench --site demo.smagri.id execute erpnext.palm_mill.demo.reset --kwargs {'days': 90}" "$(argv)"
has "resets the console for 365 days" "exec -T console python scripts/seed-console-demo.py --hari 365 --reset" "$(argv)"
lacks "ignores a site from the environment" "prod.example" "$(argv)"
erp_line=$(grep -n "exec -T backend" "$ROOT/argv" | cut -d: -f1)
console_line=$(grep -n "exec -T console" "$ROOT/argv" | cut -d: -f1)
if [ "$erp_line" -lt "$console_line" ]; then ok "ERP goes first"; else bad "ERP goes first" "$erp_line < $console_line" "not so"; fi
teardown

echo "reset: a failed ERP reset leaves the console alone"
setup
touch "$ROOT/erp_fails"
out=$(run reset); rc=$?
fails "exits non-zero" "$rc"
lacks "console not reseeded" "exec -T console" "$(argv)"
teardown

echo "status"
setup
out=$(run status); rc=$?
eq "exits 0" 0 "$rc"
has "shows the image" "$OLD" "$out"
has "shows the free disk" "19G" "$out"
teardown

echo "unknown command"
setup
out=$(run frobnicate); rc=$?
fails "exits non-zero" "$rc"
has "prints usage" "upgrade" "$out"
teardown

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
