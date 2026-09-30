"""Regression table for scripts/hooks/guard.sh (the Claude Code PreToolUse guard).

Run from anywhere: python3 scripts/hooks/test_guard.py
Exit 0 when every case behaves as expected, 1 otherwise. Add a row whenever the
guard lets something through that it should not, or blocks real work.
Run it with /usr/bin/python3 (3.9 on a stock Mac) as well as a newer Python: the hook
runs under the first python3 on PATH.
"""

import json
import pathlib
import subprocess
import sys

GUARD = pathlib.Path(__file__).resolve().parent / "guard.sh"

AI_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"

CASES = [
    # plan Task 3 Step 4 (first seven BLOCK, last five ALLOW)
    ("docker compose -f docker-compose.prod.yml down -v", "BLOCK"),
    ("git push -f origin staging", "BLOCK"),
    ("make reset-data-fresh", "BLOCK"),
    ("rm -rf artifacts/line-1", "BLOCK"),
    ("BACKEND_URL=https://api.smagri.id make console", "BLOCK"),
    ("cat media.env", "BLOCK"),
    ("git commit -m 'x' -m '" + AI_TRAILER + "'", "BLOCK"),
    ("make restart", "ALLOW"),
    ("make console", "ALLOW"),
    (".venv/bin/pytest tests/unit/ -q", "ALLOW"),
    ("make reset-data", "ALLOW"),
    ("cat docs/rules.md", "ALLOW"),
    # chained / wrapped forms a prefix rule cannot see
    ("cd ~/x && make reset-data-fresh", "BLOCK"),
    ("autograde reset-data-fresh", "BLOCK"),
    ("./autograde.sh reset-data-fresh", "BLOCK"),
    ("bash -c 'make reset-data-fresh'", "BLOCK"),
    ('echo "$(make reset-data-fresh)"', "BLOCK"),
    ("docker compose -f docker-compose.prod.yml down --volumes", "BLOCK"),
    ("docker-compose down -v", "BLOCK"),
    ("ssh pabrik 'docker compose down -v'", "BLOCK"),
    ("git push --force-with-lease origin staging", "BLOCK"),
    ("git push origin +staging", "BLOCK"),
    # final review Important 1: global git options and an absolute git path before push
    ("git -C /Users/x/autograde push --force origin staging", "BLOCK"),
    ("git -c user.name=x push -f origin staging", "BLOCK"),
    ("/usr/bin/git push --force origin staging", "BLOCK"),
    ("git --no-pager -C /tmp/r push --force-with-lease", "BLOCK"),
    ("git -C /Users/x/autograde push -u origin docs/tidy-ai-docs", "ALLOW"),
    ("git -C /Users/x/autograde log -f", "ALLOW"),
    ("rm -rf artifacts", "BLOCK"),
    ("rm -rf ./state", "BLOCK"),
    ("rm -r state/line-1", "BLOCK"),
    ("sudo rm -rf /opt/palmgrade/autograde/artifacts", "BLOCK"),
    ("rm -rf models/release", "BLOCK"),
    ("rm -rf engines", "BLOCK"),
    ("for l in 1 2 3; do rm -rf artifacts/line-$l; done", "BLOCK"),
    ("export BACKEND_URL=https://api.smagri.id", "BLOCK"),
    ('echo "BACKEND_URL=https://api.smagri.id" >> .env', "BLOCK"),
    ("docker run -e BACKEND_URL=https://api.smagri.id img", "BLOCK"),
    ("tail -n 5 .env", "BLOCK"),
    ('cat "media.env"', "BLOCK"),
    ("cat /opt/palmgrade/autograde/.env", "BLOCK"),
    ("grep SECRET .env", "BLOCK"),
    ("cat .env.production", "BLOCK"),
    ("head .env.bak-1055", "BLOCK"),
    ("cat .env.local", "BLOCK"),
    ("git commit -F - <<'EOF'\nfix: x\n\n" + AI_TRAILER + "\nEOF", "BLOCK"),
    ('gh pr create --title x --body "done\n\nGenerated with [Claude Code](https://claude.com)"', "BLOCK"),
    # legitimate work that mentions a forbidden word
    ("cat .env.example", "ALLOW"),
    ("cat media.env.example", "ALLOW"),
    ('grep -rn "reset-data-fresh" Makefile docs/', "ALLOW"),
    ("grep -rn BACKEND_URL src/palmgrade/core/config.py", "ALLOW"),
    ("docker compose down", "ALLOW"),
    ("git push -u origin docs/tidy-ai-docs", "ALLOW"),
    ("git push origin fix/a-f-b", "ALLOW"),
    ("rm -rf .pytest_cache build/", "ALLOW"),
    ("rm -f /tmp/ag-rules.md", "ALLOW"),
    ("make line N=2", "ALLOW"),
    ("make demo", "ALLOW"),
    ("BACKEND_URL=http://127.0.0.1:8100 make line", "ALLOW"),
    ("ls state/line-1 artifacts", "ALLOW"),
    ("curl -s :8001/health/detail", "ALLOW"),
    ('grep -rn "Co-Authored-By" .github/', "ALLOW"),
    # text that is only a message (commit, PR body) is not a command...
    ('git commit -m "docs: never run make reset-data-fresh on the factory PC"', "ALLOW"),
    ("git commit -m 'docs: rm -rf artifacts is blocked by the hook'", "ALLOW"),
    (
        "gh pr create --base staging --body \"$(cat <<'EOF'\n## What\nblocks docker compose down -v\n"
        + "and BACKEND_URL=https://api.smagri.id\nEOF\n)\"",
        "ALLOW",
    ),
    ("git commit -F - <<'EOF'\ndocs: make reset-data-fresh stays manual\nEOF", "ALLOW"),
    # ...but text the shell executes, even inside quotes, still is.
    ('git commit -m "note `make reset-data-fresh`"', "BLOCK"),
    ("sh -c 'rm -rf state'", "BLOCK"),
    ("ssh pabrik <<'EOF'\ncd /opt/palmgrade/autograde && rm -rf artifacts\nEOF", "BLOCK"),
]


def run(tool_name, tool_input):
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    return subprocess.run([str(GUARD)], input=payload, text=True, capture_output=True)


def main():
    bad = 0
    for cmd, want in CASES:
        r = run("Bash", {"command": cmd})
        got = {0: "ALLOW", 2: "BLOCK"}.get(r.returncode, "EXIT" + str(r.returncode))
        ok = got == want
        bad += not ok
        print(("ok " if ok else "BAD") + " " + want.ljust(5) + " got " + got.ljust(6) + " " + cmd.replace("\n", "\\n"))

    # Any other tool passes untouched.
    if run("Read", {"file_path": ".env"}).returncode != 0:
        print("BAD non-Bash tool call not allowed")
        bad += 1

    if bad:
        print("guard: " + str(bad) + " mismatches")
        return 1
    print("guard: " + str(len(CASES)) + "/" + str(len(CASES)) + " cases as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
