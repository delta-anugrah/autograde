#!/usr/bin/env bash
# Smoke-test the local operator console: the lock in front of it, every endpoint the
# UI calls, plus the three traps that have bitten before - net summed rather than
# multiplied, the weight floor, and the no-truck row being kept.
#
# Read-only apart from one sign-in and one deliberately invalid weighing POST, which
# is expected to be rejected and therefore writes nothing.
#
# Since Fase 4 the console API needs a session. The signed-in checks run only when
# an operator is given (make one with `make operator`); without one, only the lock
# itself is checked:
#   CONSOLE_EMAIL=operator@pks.test CONSOLE_SANDI=<sandi> scripts/smoke-console.sh
#
# Seed some data first, or the recap checks have nothing to look at:
#   SEED_CONFIRM=1 python3 scripts/seed-console-demo.py
#
# Usage: scripts/smoke-console.sh [base-url]      default http://localhost:8000
set -u
BASE="${1:-http://localhost:8000}"
pass=0; fail=0
JAR="$(mktemp)"
trap 'rm -f "$JAR" /tmp/smoke-recap.json /tmp/smoke-weigh.json' EXIT

check() { # check <name> <want> <got>
  if [ "$2" = "$3" ]; then printf '  ok   %-44s %s\n' "$1" "$3"; pass=$((pass+1))
  else printf '  FAIL %-44s got %s, want %s\n' "$1" "$3" "$2"; fail=$((fail+1)); fi
}
anon() { curl -s -o /dev/null -w '%{http_code}' "$BASE$1"; }
code() { curl -s -o /dev/null -w '%{http_code}' -b "$JAR" "$BASE$1"; }
finish() { echo; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]; exit; }

echo "== open to anyone =="
for p in /health /console /api/console/operators; do
  check "GET $p" 200 "$(anon "$p")"
done

echo "== shut until someone signs in (Fase 4) =="
for p in /api/console/state /api/console/history /api/console/trucks \
         /api/console/weighings /api/console/recap; do
  check "GET $p without a session" 401 "$(anon "$p")"
done

echo "== the page really is the file on disk =="
# Bind-mounted HTML is served fresh; a mismatch means the mount is gone and the
# container is serving a copy baked into the image.
check "console.html matches the working tree" same \
  "$(if [ "$(curl -s "$BASE/console" | md5sum | cut -d' ' -f1)" = \
          "$(md5sum src/palmgrade/static/console.html | cut -d' ' -f1)" ]; \
     then echo same; else echo STALE; fi)"

if [ -z "${CONSOLE_EMAIL:-}" ] || [ -z "${CONSOLE_SANDI:-}" ]; then
  echo "== signed-in checks skipped: set CONSOLE_EMAIL and CONSOLE_SANDI (make operator) =="
  finish
fi

echo "== sign in =="
# Built in Python and piped on stdin, so the password never shows up in the process list.
login_code="$(python3 -c '
import json, os
print(json.dumps({"email": os.environ["CONSOLE_EMAIL"].strip().lower(),
                  "sandi": os.environ["CONSOLE_SANDI"]}))
' | curl -s -o /dev/null -w '%{http_code}' -c "$JAR" -H 'content-type: application/json' \
      --data @- "$BASE/api/console/login")"
check "POST /api/console/login as $CONSOLE_EMAIL" 200 "$login_code"
[ "$login_code" = 200 ] || finish

echo "== endpoints the UI calls =="
for p in /api/console/me /api/console/state /api/console/history \
         /api/console/trucks /api/console/weighings /api/console/recap; do
  check "GET $p" 200 "$(code "$p")"
done

echo "== recap traps =="
curl -s -b "$JAR" "$BASE/api/console/recap"    -o /tmp/smoke-recap.json
curl -s -b "$JAR" "$BASE/api/console/weighings" -o /tmp/smoke-weigh.json
read -r r_notruck r_sum <<EOF
$(python3 - <<'PY'
import json
recap = json.load(open("/tmp/smoke-recap.json"))["items"]
weigh = json.load(open("/tmp/smoke-weigh.json"))["items"]

# A bunch graded before its truck was assigned must stay visible, not be dropped.
notruck = "yes" if any(r["truck_id"] is None for r in recap) else "no"

# One truck, two tickets in a day: the recap must ADD the nets. A SQL JOIN here
# would instead multiply the bunch count by the ticket count.
tickets = {}
for t in weigh:
    tickets.setdefault(t["truck_id"], []).append(t["neto_kg"])
multi = next((k for k, v in tickets.items() if k and len(v) > 1), None)
if multi is None:
    summed = "no-2-ticket-truck"          # seeder did not run
else:
    want = sum(tickets[multi])
    got = next((r["neto_kg"] for r in recap if r["truck_id"] == multi), None)
    summed = "sum" if got is not None and abs(got - want) < 0.01 else f"{got}!={want}"
print(notruck, summed)
PY
)
EOF
check "no-truck row kept" yes "$r_notruck"
check "2-ticket truck sums its net" sum "$r_sum"

echo "== weight floor (must be rejected, so nothing is written) =="
# "14.820" typed for fourteen tons parses cleanly to 14.82 kg. Nothing in the
# payload contradicts it, so a floor is the only thing that catches the typo.
check "bruto '14.820' rejected" 400 \
  "$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -X POST "$BASE/api/console/weighings" \
     -H 'content-type: application/json' \
     -d '{"ref":"SMOKE-FLOOR","plate_number":"KT 2509 ABC","bruto_kg":"14.820","tara_kg":"4.200"}')"

curl -s -o /dev/null -b "$JAR" -X POST "$BASE/api/console/logout"
finish
