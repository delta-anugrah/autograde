# Review checklist (before every PR to `staging`)

Used by the `rule-reviewer` subagent and by humans. Report violations only; do not rewrite code.

## A. Rules (`CLAUDE.md` §3, full text `docs/rules.md`)
- [ ] Layer rule kept: route, controller, service, repository/pipeline/integration; console without controller.
- [ ] Detection workers never POST events; they write to disk and the outbox, and only `OutboxRetryWorker` and `BatchUploadWorker` send them (rule 1). Console workers (AutoERP, sync checks, line status) call the network by design.
- [ ] The detection thread never waits for disk: PLC pulse, `processed` marks and the `timestamp` stay on the detection path (rule 1b).
- [ ] Geometry in stream space; capture line and ROI not confused (Conventions).
- [ ] Any change to a rule's behaviour updates `docs/rules.md` under the same number and the index line in `CLAUDE.md`.
- [ ] A new env var has a default in `core/config.py`, is in `docker-compose*.yml`, and skill `compose-host-pabrik` was consulted if the factory must receive it.
- [ ] Screen text and docs without em dash; frontmatter without `: ` in `description`.
- [ ] Commits and PR text in English, `<type>(<scope>): ...`, no AI mention.

## B. Never-do (`CLAUDE.md` §4)
- [ ] No torch/cv2 import reachable from `console_main.py` or from tests.
- [ ] No `BACKEND_URL` pointing at the cloud in any file, example or doc added.
- [ ] No `down -v`, force-push, `reset-data-fresh`, `rm -rf artifacts|state` in scripts or docs added.

## C. Tests and evidence
- [ ] New logic has a pure-logic test in `tests/unit/`; HTTP-only bits use a test-assembled app, never `create_console_app()`.
- [ ] The final report shows `pytest` and `ruff` output. "Tests pass" without output = not validated.
- [ ] Anything not run is listed under *Not validated*.

## D. Docs
- [ ] Paths named in new markdown exist (`tests/unit/test_doc_links.py` would tell you).
- [ ] `docs/PROGRESS.md` has an entry for this work.

## Output format
```
VIOLATIONS (blocking):   file:line, rule, what to change
WARNINGS (non-blocking): ...
EVIDENCE CHECK:          commands with output / claims without output
```
