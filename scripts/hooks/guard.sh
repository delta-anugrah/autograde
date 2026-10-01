#!/usr/bin/env bash
# Claude Code PreToolUse hook for Bash; the rules are in guard.py next to this file.
# Kept as a separate .py because macOS bash 3.2 misparses quotes in a heredoc
# nested in "$(...)", and a hook that fails to parse exits 2 = blocks every command.
exec python3 "$(dirname "$0")/guard.py"
