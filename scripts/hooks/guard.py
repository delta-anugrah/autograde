"""Claude Code PreToolUse hook for Bash (run by guard.sh).

Reads the tool call as JSON on stdin and blocks (exit 2) commands that CLAUDE.md §4
forbids. Prefix-only permission rules cannot see flags in the middle of a command;
this regex check can. Exit 0 lets the call through.

The rules match only where a shell would run a command. Before matching, `expose()`
rewrites the command so that text which is only data (a commit message, a PR body, a
heredoc fed to `git commit -F -`) can no longer look like a command start, while text
the shell does execute (`$(...)`, backticks, `sh -c '...'`, `ssh host '...'`, a heredoc
fed to a shell or ssh) is kept as commands. The one rule that reads data on purpose is
the AI trailer check: a commit message or PR body is exactly where that text is banned.

Copied from autoerp/scripts/hooks/guard.py (expose machinery unchanged); the rules are
autograde's. Must run on Python 3.9 (Apple's python3 on a stock Mac).
"""

import json
import re
import sys

# A command word starts the line or follows a separator (; & | ( newline). So
# cd ~/x && make reset-data-fresh is caught while grep for the words
# reset-data-fresh (a search, not a run) is not.
START = r"(?:^|[;&|(\n]\s*)"
# Before the command word may sit any number of wrappers that still run it: VAR=val,
# shell keywords (do/then/else), sudo/env/time/nohup/exec, ssh <host>, docker
# [compose] exec|run <container>, and bash/sh/zsh -c or -lc.
_ARGS = r"(?:-\S+\s+(?:[^-\s]\S*\s+)?)*"  # flags, each with an optional value
WRAP = (
    r"(?:\w+=\S*\s+"
    + r"|(?:do|then|else)\s+"
    + r"|(?:sudo|env|time|nohup|exec|command)\s+" + _ARGS + r"(?:\w+=\S*\s+)*"
    + r"|ssh\s+" + _ARGS + r"\S+\s+"
    + r"|docker(?:-compose|\s+compose)?\s+" + _ARGS + r"(?:exec|run)\s+" + _ARGS + r"\S+\s+"
    + r"|(?:ba|z)?sh\s+-\w*c\s+"
    + r")*"
)
START += WRAP
SEG = r"[^;&|\n]*"  # the rest of one command, up to the next separator

# What comes right before a quote whose contents a shell will run.
_SHELL_C = re.compile(r"(?:^|[\s;&|(])(?:\S*/)?(?:ba|z|da)?sh\s+(?:-\w+\s+)*-\w*c\s*$")
_SSH_HOST = re.compile(r"(?:^|[\s;&|(])ssh\s+" + _ARGS + r"[^-\s]\S*\s+$")
# A heredoc fed to one of these is commands, not data.
_FEEDS = re.compile(r"(?:^|[\s;&|(])(?:(?:\S*/)?(?:ba|z|da)?sh|ssh)\b")
_HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([\w.-]+)\2")
_SEPARATORS = re.compile(r"[;&|()<>\n`]")


def _skip_quote(text, i):
    """Index just past the quote opened at text[i], or None when it never closes."""
    q, j = text[i], i + 1
    while j < len(text):
        if q == '"' and text[j] == "\\":
            j += 2
            continue
        if q == '"' and text.startswith("$(", j):
            j = _close_paren(text, j + 1) + 1
            continue
        if text[j] == q:
            return j + 1
        j += 1
    return None


def _heredoc_bodies(text, j, pending):
    """Read one body per pending heredoc from index j; return (bodies, index after them)."""
    bodies = []
    for delim, dash, *_ in pending:
        start = j
        while True:
            nl = text.find("\n", j)
            line = text[j:] if nl < 0 else text[j:nl]
            if (line.lstrip("\t") if dash else line) == delim:
                bodies.append(text[start:j])
                j = len(text) if nl < 0 else nl + 1
                break
            if nl < 0:
                bodies.append(text[start:])
                j = len(text)
                break
            j = nl + 1
    return bodies, j


def _close_paren(text, i):
    """Index of the ')' matching the '(' at text[i], skipping quotes and heredoc bodies."""
    depth, j, pending = 0, i, []
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if text.startswith("<<", j) and not text.startswith("<<<", j):
            m = _HEREDOC.match(text, j)
            if m:
                pending.append((m.group(3), m.group(1)))
                j = m.end()
                continue
        if c == "\n" and pending:
            _, j = _heredoc_bodies(text, j + 1, pending)
            pending = []
            continue
        if c in "'\"":
            k = _skip_quote(text, j)
            j = len(text) if k is None else k
            continue
        if c == "`":
            k = text.find("`", j + 1)
            j = len(text) if k < 0 else k + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(text)


def _substitutions(text, depth):
    """The $(…) and `…` inside double-quoted or unquoted-heredoc text, as commands."""
    out, j = [], 0
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text.startswith("$(", j):
            k = _close_paren(text, j + 1)
            out.append(" ; " + expose(text[j + 2 : k], depth + 1) + " ; ")
            j = k + 1
            continue
        if text[j] == "`":
            k = text.find("`", j + 1)
            k = len(text) if k < 0 else k
            out.append(" ; " + expose(text[j + 1 : k], depth + 1) + " ; ")
            j = k + 1
            continue
        j += 1
    return "".join(out)


def expose(text, depth=0):
    """Rewrite text so that only what a shell would run can start a command."""
    if depth > 8:
        return text
    out, pending, j = [], [], 0
    while j < len(text):
        c = text[j]
        if c == "\\":
            out.append(text[j : j + 2])
            j += 2
            continue
        if text.startswith("<<", j) and not text.startswith("<<<", j):
            m = _HEREDOC.match(text, j)
            if m:
                segment = re.split(r"[;&|\n(]", "".join(out))[-1]
                pending.append((m.group(3), m.group(1), bool(m.group(2)), bool(_FEEDS.search(segment))))
                out.append(" ")
                j = m.end()
                continue
        if c == "\n" and pending:
            out.append("\n")
            bodies, j = _heredoc_bodies(text, j + 1, pending)
            # No zip(strict=True): the hook runs under whatever `python3` is first on PATH,
            # which is Apple's 3.9 on a stock Mac, and a crash there lets the command through.
            if len(bodies) != len(pending):
                raise ValueError("heredoc bodies do not match their markers")
            for i, (_, _, quoted, feeds) in enumerate(pending):
                body = bodies[i]
                if feeds:
                    out.append(expose(body, depth + 1) + "\n")
                elif not quoted:
                    out.append(_substitutions(body, depth))
            pending = []
            continue
        if c == "`":
            k = text.find("`", j + 1)
            k = len(text) if k < 0 else k
            out.append(" ; " + expose(text[j + 1 : k], depth + 1) + " ; ")
            j = k + 1
            continue
        if text.startswith("$(", j):
            k = _close_paren(text, j + 1)
            out.append(" ; " + expose(text[j + 2 : k], depth + 1) + " ; ")
            j = k + 1
            continue
        if c in "'\"":
            k = _skip_quote(text, j)
            if k is None:  # unterminated: keep it as commands rather than let it through
                out.append(" ; " + expose(text[j + 1 :], depth + 1))
                break
            inner = text[j + 1 : k - 1]
            before = "".join(out)
            if _SHELL_C.search(before) or _SSH_HOST.search(before):
                out.append(" ; " + expose(inner, depth + 1) + " ; ")
            else:
                # Data: keep the words (a quoted path still matches), drop what could
                # start a command, and keep any substitution the shell would run.
                out.append(_SEPARATORS.sub(" ", inner.replace('\\"', " ")))
                if c == '"':
                    out.append(_substitutions(inner, depth))
            j = k
            continue
        out.append(c)
        j += 1
    return "".join(out)


# End of a path word: whitespace, end, a separator, or a redirection.
_END = r"(?=\s|$|[;&|)<>])"
# Evidence and model folders of a line, relative (./state) or under an autograde checkout.
_EVIDENCE = r"\s(?:\S*/autograde/|\./)?(?:artifacts|state|models|engines)(?=/|\s|$|[;&|)])"
_CLOUD_BACKEND = r"BACKEND_URL=\S*smagri\.id"

RULES = [
    (
        START + r"docker(?:-compose|\s+compose)\b" + SEG + r"\bdown\b" + SEG + r"(\s-v\b|--volumes\b)",
        "docker compose down -v destroys volumes (CLAUDE.md §4).",
    ),
    (
        START + r"(?:\S*/)?git(?:\s+(?:-[Cc]\s+\S+|--\S+))*\s+push\b" + SEG + r"\s(--force\b|-f\b|--force-with-lease\b|\+\S)",
        "force-push is forbidden (CLAUDE.md §4).",
    ),
    (
        START + r"(?:\S*/)?(?:make|autograde(?:\.sh)?|palmgrade(?:\.sh)?)\b" + SEG + r"\breset-data-fresh\b",
        "reset-data-fresh deletes every photo and database; only the user runs it by hand. "
        + "`make reset-data` shows what it would delete (CLAUDE.md §4).",
    ),
    (
        START + r"(?:\S*/)?rm\b(?=" + SEG + r"\s(?:-\w*[rR]\w*|--recursive)\b)" + SEG + _EVIDENCE,
        "artifacts/, state/, models/ and engines/ hold evidence, databases and models; "
        + "use `make reset-data` first (CLAUDE.md §4).",
    ),
    (
        START + r"(?:export\s+)?" + _CLOUD_BACKEND,
        "BACKEND_URL must be the local console, never the cloud (CLAUDE.md §4).",
    ),
    (
        START + r"(?:echo|printf|tee|sed)\b" + SEG + _CLOUD_BACKEND,
        "BACKEND_URL must be the local console, never the cloud (CLAUDE.md §4).",
    ),
    (
        START + r"docker\b" + SEG + r"\s(?:-e|--env)(?:\s+|=)" + _CLOUD_BACKEND,
        "BACKEND_URL must be the local console, never the cloud (CLAUDE.md §4).",
    ),
    (
        START + r"(?:cat|less|more|head|tail|bat|grep)\b" + SEG + r"(?:\s|/)(?:media)?\.env(?:\.(?:local|production|bak\S*))?" + _END,
        "do not print .env or media.env (secrets) (CLAUDE.md §4).",
    ),
]

# Commit messages and PR text must not mention AI (CLAUDE.md §3 Git). This reads the
# raw command on purpose: the trailer lives in the message, which expose() treats as data.
_AI_TEXT = re.compile(r"Co-Authored-By:\s*Claude|Generated with \[?Claude Code", re.IGNORECASE)
_AI_CMD = START + r"(?:git\s+(?:commit|tag|merge)|gh\s+pr\s+(?:create|edit|merge))\b"


def _blocked(why, cmd):
    print("BLOCKED by scripts/hooks/guard.sh: " + why + "\nCommand: " + cmd, file=sys.stderr)
    return 2


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "Bash":
        return 0
    cmd = data.get("tool_input", {}).get("command", "")
    code = expose(cmd)
    for pattern, why in RULES:
        if re.search(pattern, code):
            return _blocked(why, cmd)
    if _AI_TEXT.search(cmd) and re.search(_AI_CMD, code):
        return _blocked("commit messages and PR text must not mention AI (CLAUDE.md §3 Git).", cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
