#!/usr/bin/env bash
# demo-autograde-ci: the only thing the GitHub Actions key may run on the droplet.
#
#   authorized_keys: command="/usr/local/bin/demo-autograde-ci",restrict ssh-ed25519 AAAA... demo-deploy
#
# This droplet also runs production AutoERP, so anything but `status` or `upgrade vX.Y.Z` is
# refused (exit 2), and one deploy runs at a time: a second tag while the first still runs gets
# exit 75 and changes nothing. Tests: deploy/demo/demo-autograde-ci.test.sh.
set -euo pipefail

DEMO_AUTOGRADE=${DEMO_AUTOGRADE:-/usr/local/bin/demo-autograde}
LOCK=${LOCK:-/tmp/demo-autograde-ci.lock}
cmd=${SSH_ORIGINAL_COMMAND:-}

if [[ $cmd == status ]]; then
	exec "$DEMO_AUTOGRADE" status
fi
if [[ $cmd =~ ^upgrade\ (v[0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
	versi=${BASH_REMATCH[1]}
	exec 9>"$LOCK"
	flock -n 9 || { echo "another demo deploy is running" >&2; exit 75; }
	# 9>&-: the upgrade must not inherit the lock fd, or a container it starts would hold the
	# lock after this script ends (same trap as the factory updater's 8>&-).
	"$DEMO_AUTOGRADE" upgrade "$versi" 9>&-
	exit $?
fi
echo "refused: only 'status' or 'upgrade vX.Y.Z'" >&2
exit 2
