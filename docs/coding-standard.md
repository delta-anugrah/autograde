# Coding standard: autograde

Loaded into every Claude Code session by the import line in `CLAUDE.md`; people read it before
writing code too. One line per rule, cited by id in reviews (`docs/REVIEW-CHECKLIST.md` §E). The
reasons behind numbered rules are in `docs/rules.md`, the design in `docs/overview.md`. Code paths
below are under `src/palmgrade/`.

It applies to new code and to code you change. The known gaps at the end are fixed in their own
PRs; a PR is not blocked by a gap it did not add.

## Logic: where things live

- **L1.** Layers: line app `route → controller → service → repository / pipeline / integration`; console `route → service → repository`, no controller on purpose. What each layer may do: `docs/overview.md` §1.
- **L2.** Business rules are pure functions or dataclasses in `domain/`: no I/O and no `fastapi`, `httpx` or `cv2` import, so a unit test covers them without a server.
- **L3.** SQL lives only in storage modules: `repositories/`, the `*_store.py` files, `integrations/upload/upload_manifest.py` and `license/local_repo.py`. Routes, services and workers never hold a query.
- **L4.** The backend computes and decides anything that counts: verdicts, net weight (rule 15), what AutoERP receives, who may do what (rule 21). The screen formats what it is given; in new code a rate or total shown on screen comes from the backend.
- **L5.** Evidence first: write to disk or an outbox, then a worker sends it (rule 1). The detection thread never waits for disk or network (rule 1b).
- **L6.** No `except Exception` or bare `except` that passes in silence: log it or re-raise. A narrow, expected exception may pass with a comment saying why, as `queue.Empty` in the drop-old queues (`docs/overview.md` §2).
- **L7.** A failure that stops data from arriving shows on the console (status, queue, ribbon), not only in a log: the factory PC is reachable only over AnyDesk.

## Style

- **S1.** Names: Python modules and functions may keep a factory concept in Indonesian (`janjang`, `garis_capture`, `penjaga_ai`) while technical terms stay English (`worker`, `repository`, `health`). Database columns and new API paths are English; screen text goes through `KAMUS` (F6). Casing as in `CLAUDE.md` Conventions. Existing names stay.
- **S2.** A timeout, limit, threshold or retry delay is a named constant, never a bare number inside the logic.
- **S3.** One function, one job: if its description needs "and", split it. New functions carry type hints.
- **S4.** Comments and docstrings say why; the code already says what.
- **S5.** A Python file you create or change passes `ruff check src/ tests/`, which CI runs on the whole code base.
- **S6.** A new dependency needs a reason in the PR and a pin in `requirements.txt`; nothing the console imports may pull in torch or cv2.

## Backend

- **B1.** Check every input where it enters, before it reaches a service: an HTTP body with a Pydantic model in `schemas/` that fixes its shape only, while content rules stay in the domain and keep their codes (a wrong shape is 400 `input_tidak_sah`); scanner text, CSV rows and AutoERP documents with a pure parser in `domain/` that rejects what it does not recognise (as `baca_qr` in `domain/qr.py`). New routes never take `Annotated[dict, Body()]`; the only ones left are the four support-setting routes, whose domain parsers already check every field with their own codes (setelan rekam reads `"8"` as 8 and ignores fields from a newer screen, setelan grading and sumber kamera refuse unknown ones), and the machine lane with its frozen contract (`tests/unit/test_console_body_schema.py`). Escaping is for output (F7), not input.
- **B2.** New endpoints: a noun for data (`GET` or `POST /api/console/trucks`), `POST .../{id}/<verb>` for an action (as `/lines/{line_code}/assign-truck`), English path words, errors as `HTTPException` with the right status code. Never rename an existing path (C2). Calls to AutoERP follow `autoerp/docs/autograde-integration.md`, not REST.
- **B3.** Every send between systems (line to console, console to AutoERP, photos to R2) is safe to repeat: `event_id` is uuid5 (rule 1), and a truck visit is resent whole, never patched (rule 18).
- **B4.** Every outbound call has a timeout; retries back off exponentially up to a ceiling, and factory data is never dropped after N failures (rule 31).
- **B5.** A SQLite schema change runs by itself at start-up, is safe to run twice, and adds rather than renames or drops: a factory PC can go back to an older image. Values are always bound parameters (`?` or `:name`); an f-string only assembles SQL from code constants.
- **B6.** Writes that belong together share one transaction; columns you filter on get an index; no query inside a loop (N+1). Heavy SQLite work in a console route stays off the event loop (rule 30).
- **B7.** Config and secrets come from env vars through `Settings` in `core/config.py`. A new env var gets a default there and goes into the compose files (skill `compose-host-pabrik` when the factory must receive it). Secrets never appear in code, commits, logs or transcripts.
- **B8.** Every console route that is not public on purpose checks its caller on the server: people through a role guard (`require_operator`, `require_support`), the lines through the shared secret (`rahasia_cocok`, rule 28). Passwords stay hashed (scrypt for local accounts, pbkdf2 from AutoERP) and the login lockout stays.
- **B9.** Everything that leaves the factory (AutoERP, R2) goes over HTTPS. The console on the factory LAN is HTTP today; changing that is its own decision.
- **B10.** Slow work runs in a worker under `workers/`, whose `run_loop` wraps `run_once` in try/except (rule 6); a request never waits for it.
- **B11.** Logs carry context (line, truck or event id) at the right level; health is exposed in `/health` and `/health/detail`.

## Frontend (`static/console.html`)

- **F1.** One file, vanilla JS, no build, no CDN, zero `https://`: the screen must work with the internet down.
- **F2.** One render function per part of the screen (line card, tab, table), as `kartuLine`; loading and computing stay out of render functions.
- **F3.** The screen never decides or computes what counts (L4). Hiding a support control is only tidiness; the lock is the backend guard (`require_support`, 403, rule 21).
- **F4.** Every view that loads data handles five states: loading, error, empty, content, and disconnected (camera, line or AutoERP unreachable).
- **F5.** Colours and spacing come from the CSS variables in `:root` (light and dark theme); text reads from metres away; buttons in one row share one width.
- **F6.** All screen text goes through `KAMUS` (id and en), with no em dash, no spaced hyphen as a pause, and verbs that match the button labels (`tests/unit/test_console_copy.py`). Outside the Log tab no system error text: no HTTP status, URL, raw server or exception text, env or file name, or error code; a failure is worded from a code, and an unknown code gets the generic sentence (`alasan`, rule 21, `tests/unit/test_console_html_teks_ramah.py`).
- **F7.** Text from the server or from the operator reaches `innerHTML` only through `esc()`; a number goes through `Number()` or `kg()` first.
- **F8.** A POST that changes data runs inside `denganSibuk(`: spinner on, second click refused (`tests/unit/test_console_tombol_sibuk.py`).
- **F9.** A timer that belongs to one tab starts and stops in `bukaTabDev` (rule 21); the screen-wide polls (`refresh`, `muatTrucks`, `muatTimbangan`) run on every tab on purpose (rules 22, 24, 27). A poll that rewrites a view uses `tulisKalauBeda`, so an unchanged view is not redrawn.
- **F10.** No secret, API key or licence token in the page. What must survive a reload (the open tab) sits in `localStorage`; data always comes back from the server.
- **F11.** One button component: the base `button`, `button.utama` for the main action of a step, `button.bahaya` for every cancel, delete, reset, undo, release or sign-out (`bahaya pekat` for the final irreversible run); never a one-off colour rule (`tests/unit/test_console_tombol_bahaya.py`). A successful action answers with a toast (`toastSukses`; saved but not reached everywhere = `toastPeringatan`), never a box of text that looks like a warning.
- **F12.** No native browser dialog (`confirm`, `alert`, `prompt`): every "are you sure?" goes through `tanyaKonfirmasi()`, the one in-page `<dialog>`, whose Batal is `button.bahaya` like every other cancel (F11, user 2026-10-03) and keeps the first focus, so an accidental Enter still cancels (`tests/unit/test_console_html_konfirmasi.py`).

## Tests

- **T1.** Test first: new logic gets a failing pure-logic test in `tests/unit/` before the code; a bug fix starts with a test that reproduces it.
- **T2.** Tests never need torch, cv2, the camera SDK or a GPU; HTTP-only bits use an app assembled in the test, never `create_console_app()`.
- **T3.** A console change gets a test in `tests/unit/test_console_html_*.py`; a change to something an operator clicks through also gets or updates a browser test in `tests/browser/` (Playwright, Firefox and Chromium, required in CI; `make test-browser`). Looks that a test cannot judge are checked by eye in a real browser (skill `konsol-autograde`, never on ports 8100 or 8001).
- **T4.** The final report pastes `pytest` and `ruff` output; a claim without output counts as not validated.

## Factory PCs already installed

- **C1.** An old `.env` keeps working: a new env var has a default, and a renamed one is still read under its old name.
- **C2.** Container names, the local image tag and the package name never change (`CLAUDE.md` §1), and neither do existing endpoint paths (B2).
- **C3.** A new build opens the SQLite files an older build wrote and upgrades them on start (B5), with no manual step on the factory PC.

## Docs

- **D1.** One fact, one home: `CLAUDE.md` indexes, `docs/rules.md` holds the full rule text, this file the coding standard, `docs/overview.md` the design. Point to a fact; never copy it.
- **D2.** A behaviour change updates its doc in the same PR: `docs/rules.md` under the same number plus the `CLAUDE.md` index line, `docs/backend-overview.md` for endpoints and env vars, `docs/MANUAL.md` for what an operator sees.
- **D3.** New docs are in English, operator manuals in Indonesian; no em dash and no spaced hyphen as a pause outside code; every path a doc names exists (`tests/unit/test_doc_links.py`, and `tests/unit/test_coding_standard.py` for this file).
- **D4.** Every task prepends its final report to `docs/PROGRESS.md`; `CLAUDE.md` stays at 200 lines or fewer.

## Not used here, on purpose

- Microservices or a message broker: one factory PC, often offline; the lines and the console are one image run four times.
- React, TypeScript, an npm build, TanStack Query, or filters kept in the URL: the console is one offline file on a kiosk with no address bar.
- Rate limiting every request: a LAN console with a handful of users; the login lockout covers password guessing.
- Moving passwords to bcrypt or argon2: scrypt and pbkdf2 are already on the OWASP list.

## Known gaps (each fixed in its own PR)

| Gap | Where | Rule |
|---|---|---|
| Outbox schema changes are ad-hoc blocks with no version number (`console.db` carries `PRAGMA user_version` since batch 4.5) | `integrations/erp/outbox_store.py`, `integrations/outbox/outbox_store.py` | B5, C3 |
| The console column renames date from developer machines | `repositories/console_skema.py` | B5, C3 |
| A silent `except Exception: pass` | `workers/frame_capture_worker.py`, `pipelines/realtime_inspection_pipeline.py` | L6 |
| The ripe rate and the yard totals across lines are computed on the screen | `static/console.html` (`isiTally`, `rasioRiwayat`) | L4, F3 |
| Ruff runs with rules E, F, I, UP, B only | `pyproject.toml` | S5 |
| No JS linter; the node-based console tests skip themselves where node is missing | `static/console.html` | T3 |
| Path words mix languages (`/history` next to `/riwayat`) | `routes/console.py` | B2 (new paths only, never rename) |
