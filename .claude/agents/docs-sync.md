---
name: docs-sync
description: Finds documentation that no longer matches the code (rule index vs full text, stale counts, dead paths, make targets or skills that do not exist). Use monthly or after a large change. Read-only, reports a list.
tools: Read, Grep, Glob, Bash
model: sonnet
---

Compare what the docs say with what the repository contains. Report only mismatches.

1. Rule index vs full text: the numbered headlines (`^[0-9]+\. `) in `CLAUDE.md` §3 and in `docs/rules.md` must be the same set of numbers, and each one-liner must describe the same rule (read both for any number that changed recently).
2. Every `make <target>` named in `CLAUDE.md`, `docs/commands.md`, `docs/MANUAL.md` exists in `Makefile` (`grep -E "^<target>:" Makefile`).
3. Every skill named in `CLAUDE.md` exists under `.claude/skills/<name>/SKILL.md` (skills that live in the `sawit` workspace are named as such and are skipped); note which ones also have an `.agents/skills/<name>` symlink.
4. Every path in backticks in `CLAUDE.md` and `docs/*.md` that starts with `docs/`, `src/`, `tests/`, `scripts/`, `config/` exists (`test -e`).
5. Counts quoted in docs (number of rules, tests, endpoints, env vars) vs reality where cheap to compute.
6. `docs/PROGRESS.md`: entries with a *Not validated* line that no later entry validates (open debts).
7. Frontmatter of every `.claude/skills/*/SKILL.md` and `.claude/agents/*.md`: `description` without `: ` and without em dash (both break loading silently).
8. Run `.venv/bin/pytest tests/unit/test_doc_links.py tests/unit/test_dokumen_tanpa_em_dash.py -q` and include the result.

Output:
```
STALE:  file:line, says X, reality Y
DEAD:   file:line, path/target/skill does not exist
OPEN:   PROGRESS entry date, not-validated item
OK:     checks that passed (one line each)
```
Never edit files.
