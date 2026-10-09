#!/usr/bin/env bash
# Tests demo-autograde-ci.sh, the forced command of the GitHub Actions key, with a fake
# demo-autograde that echoes its arguments: no Docker, no droplet.
#
#   bash deploy/demo/demo-autograde-ci.test.sh
#
# The one-deploy-at-a-time case needs util-linux `flock` (the droplet and CI have it, macOS
# does not); without it a stand-in that always takes the lock covers the command filter only.

set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
PASS=0
FAIL=0

printf '#!/usr/bin/env bash\necho "ran: $*"\n' >"$TMP/fake"
chmod +x "$TMP/fake"
PATH_UJI=$PATH
if ! command -v flock >/dev/null; then
	mkdir -p "$TMP/bin"
	printf '#!/usr/bin/env bash\nexit 0\n' >"$TMP/bin/flock"
	chmod +x "$TMP/bin/flock"
	PATH_UJI=$TMP/bin:$PATH
fi

run() { PATH=$PATH_UJI SSH_ORIGINAL_COMMAND="$1" DEMO_AUTOGRADE="$TMP/fake" LOCK="$TMP/lock" bash "$HERE/demo-autograde-ci.sh"; }
expect_ok() {
	local out
	if out=$(run "$1" 2>&1) && [ "$out" = "ran: $2" ]; then PASS=$((PASS + 1)); echo "  ok   $1"
	else FAIL=$((FAIL + 1)); echo "  FAIL allowed: '$1' -> '$out'"; fi
}
expect_no() {
	local out rc
	out=$(run "$1" 2>&1); rc=$?
	if [ "$rc" -eq 2 ] && ! grep -q "ran:" <<<"$out"; then PASS=$((PASS + 1)); echo "  ok   refused: '$1'"
	else FAIL=$((FAIL + 1)); echo "  FAIL refused: '$1' -> rc $rc '$out'"; fi
}

expect_ok "upgrade v1.26.2" "upgrade v1.26.2"
expect_ok "status" "status"
expect_no "upgrade v1.26.2; rm -rf /"
expect_no "upgrade v1.26.2 && reset"
expect_no 'upgrade $(reboot)'
expect_no "upgrade v1.26"
expect_no "upgrade latest"
expect_no "upgrade v1.26.2-cpu"
expect_no " upgrade v1.26.2"
expect_no "reset"
expect_no "logs"
expect_no "status; bash"
expect_no ""
expect_no "bash"

if command -v flock >/dev/null; then
	# A second tag while the first deploy still runs: refused with 75, the first one untouched.
	flock "$TMP/lock" sleep 3 &
	sleep 0.5
	out=$(run "upgrade v1.26.3" 2>&1); rc=$?
	if [ "$rc" -eq 75 ] && ! grep -q "ran:" <<<"$out"; then PASS=$((PASS + 1)); echo "  ok   second deploy waits its turn (75)"
	else FAIL=$((FAIL + 1)); echo "  FAIL second deploy: rc $rc '$out'"; fi
	wait
else
	echo "  skip second deploy (no flock here; CI runs it)"
fi

echo "passed $PASS, failed $FAIL"
[ "$FAIL" -eq 0 ]
