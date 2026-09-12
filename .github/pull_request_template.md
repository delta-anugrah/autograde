<!--
WRITE IN ENGLISH. Title, body, and review comments. Commit messages may stay
Indonesian; the PR is the part people read months later, and the MacBook and
the agents both read English.

TITLE: <type>(<scope>): <what changed, imperative, no trailing period>
  type  = feat | fix | perf | refactor | docs | test | chore | release
  scope = console | plc | vision | erp | ci | docs ...
  e.g.  feat(console): add per-truck recap tab

Keep every section. Delete a heading only if it genuinely does not apply, and
say why in one line instead of leaving it blank. Write what you actually ran
and what actually came back - not what should happen.
-->

## What changes

<!-- The concrete change, as a short list. File-level is fine; commit-level is not.
     A reviewer should know what to open before they open it. -->

-

## Why

<!-- The problem this fixes, and what it costs to not fix it.
     If it fixes something that fails silently, say how the failure looks -
     that is the part nobody can guess from the diff. -->

## How to try it

<!-- The exact commands a reviewer runs to see this working, copy-pasteable.
     Include the seed/fixture step if the feature needs data to be visible.
     Write "N/A - no runtime change" if there is genuinely nothing to click. -->

```bash
```

## Verification

<!-- What was run, on what, and the real numbers that came back.
     "Tests pass" is not verification. "271 passed, net 14,190 kg" is.
     If it was never run against real data, say so here in plain words. -->

| Check | Result |
|---|---|
| `pytest tests/unit` |  |
| `ruff check` (CI scope) |  |
| Tried against a running container |  |

## Risk / not covered

<!-- Deliberate omissions, known ceilings, anything that could bite on merge.
     Destructive commands near this change belong here with a warning.
     Migrations, data backfills and anything the factory PC must do by hand
     go here too. Write "None" if there really is nothing. -->

## Refs

<!-- Runbook section, related PRs, issue numbers - whatever the next person
     needs to find. Use "Closes #N" so the issue is tracked automatically. -->

-
