# Review checklist (before every PR to `staging`)

Used by the `rule-reviewer` subagent and by humans. Report violations only; do not rewrite code.

## A. Rules (`CLAUDE.md` §3, full text `docs/rules.md`)
- [ ] Layer rule kept: route, controller, service, repository/pipeline/integration; console without controller.
- [ ] Detection workers never POST events; they write to disk and the outbox, and only `OutboxRetryWorker` and `BatchUploadWorker` send them (rule 1). Console workers (AutoERP, sync checks, line status) call the network by design.
- [ ] The detection thread never waits for disk: PLC pulse, `processed` marks and the `timestamp` stay on the detection path (rule 1b).
- [ ] Geometry in settings space (the stream picture keeps the camera ratio, mapped per axis); capture line and ROI not confused (Conventions).
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

## E. Coding standard (`docs/coding-standard.md`; cite the rule id)
A known gap listed at the end of the standard is a warning, not a violation, unless this PR added it.
- [ ] Business rules in `domain/`, SQL only in storage modules, nothing decided on the screen (L2, L3, L4, F3).
- [ ] No broad `except` that passes in silence; a failure that stops data from arriving shows on the console (L6, L7).
- [ ] Route bodies added or changed are Pydantic models in `schemas/`; new paths follow B2; no existing path renamed (B1, B2, C2).
- [ ] Outbound calls have a timeout and a capped backoff; every send is safe to repeat (B3, B4).
- [ ] A schema change runs by itself, is safe to run twice and adds rather than renames; values are bound with `?` (B5, C3).
- [ ] Console: text reaches `innerHTML` through `esc()`, data-changing POSTs run in `denganSibuk(`, every view handles its five states (F4, F7, F8).
- [ ] New logic got its failing test first; every touched Python file passes `ruff check src/ tests/` (T1, S5).

## Output format
```
VIOLATIONS (blocking):   file:line, rule, what to change
WARNINGS (non-blocking): ...
EVIDENCE CHECK:          commands with output / claims without output
```
