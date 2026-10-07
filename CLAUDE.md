# CLAUDE.md: autograde

`AGENTS.md` is a symlink to this file; `.agents/skills/*` mirror the skills for Codex. Read at
the start of every session, so it is short. Full rule text: `docs/rules.md`. Manual for a
newcomer (Indonesian, with PDF): `docs/MANUAL.md`.

Coding standard for every change (rule ids L, S, B, F, T, C, D). Claude Code loads it through this
import; other agents read it before touching code: @docs/coding-standard.md

## 1. What this is

`autograde` is the **Python AI camera service plus the operator console**, one image run four
times: **3 line containers** (one per camera, real-time YOLO ripeness detection, ports
8001/8002/8003) and a **4th console container** (`APP_MODE=console`, `console_main.py`, no
torch/cv2, so a dead camera line never takes the operator screen down). Lines deliver detection
events to the **local console** (`BACKEND_URL`); the console sends **one message per truck visit**
to **AutoERP**. palmgrade-api and palmgrade-frontend are retired (stopped 2026-09-20).

Console port: **8100** with the factory image (`docker-compose.prod.yml`) and `make console`;
**8000** from source with `docker-compose.yml` alone (`make up`). Screen: `/console`.

Stack: Python 3.11, FastAPI + uvicorn, Ultralytics YOLO (YOLOv8 + ByteTrack), torch (CPU dev,
CUDA `cu126` prod), OpenCV, httpx, APScheduler, SQLite (`state/`), boto3 (Cloudflare R2),
Hikrobot MVS SDK (GigE camera, prod only), pymcprotocol/pymodbus (PLC, factory only).
**Docker-only**, deps pinned in `requirements.txt`.

```
src/palmgrade/
  main.py / console_main.py   line app / console app (console must never import torch or cv2)
  static/console.html         the operator screen: one file, vanilla JS, no CDN, works offline
  core/ routes/ controllers/ services/ repositories/ pipelines/ workers/ integrations/ domain/
  plc/ schemas/ license/      see docs/overview.md §1 and §12 for what each layer may do
docs/  tests/unit (pure logic, no torch/cv2)  tests/integration  tests/e2e  models/release/best.pt
```
Layer rule: `route → controller → service → repository / pipeline / integration`; the console
skips the controller on purpose (`docs/overview.md` §1).

Names that stay as they are: GHCR image `ghcr.io/delta-anugrah/autograde` (one name, no legacy,
pinned by `tests/unit/test_deploy_image_name.py`), local tag `palmgrade-vision:latest`, package
`src/palmgrade/`, container names `ripe_line_*` / `palmgrade_console` (renaming breaks the
factory PC). The repo was called `palmgrade-vision` until 2026-09-14.

## 2. Commands

Everything through `make` (Docker) from `autograde/`. Full table with all flags: `docs/commands.md`.

```bash
make up / make up-dev           # prod (SDK + GPU + TensorRT) / dev (CPU)   :  rebuild only when deps or Dockerfile change
make restart                    # code-only change (bind mount), no rebuild
make console                    # console native on the Mac at 127.0.0.1:8100;  make line N=2 for a native line
make up-console / logs-console  # console container only
make demo / demo-reset / demo-off   # showcase data, never on the factory PC
make reset-data                 # SHOW what would be deleted;  make reset-data-fresh deletes (types HAPUS)
make build-engine               # TensorRT FP16 engine, once per GPU
.venv/bin/pytest tests/unit/ -q               # pure-logic tests, no torch/cv2/SDK
.venv/bin/pytest tests/integration/ -rs       # real components without hardware
make test-browser               # Playwright on the real console, Firefox + Chromium (make browser-siap once)
.venv/bin/ruff check src/ tests/              # the whole code base, same as CI
curl :8001/health               # 503 while the AI guard says AI dead or frames stopped;  /health/detail: capture_save_dropped must be 0
```

CI (`ci.yml`) runs ruff + unit + e2e + integration, and the browser suite in Firefox and
Chromium, on every PR to `staging`/`main`, without GPU, torch, cv2 or SDK. New tests: pure
logic first; never drag hardware into CI. FastAPI `TestClient` only for the HTTP-only bits,
with an app assembled in the test, never `create_console_app()` (it opens the developer's
`state/console.db`).

## 3. Rules (index; full text and rationale in `docs/rules.md`, same numbers)

0. Model has 4 classes; a class is not a verdict. Mapping lives only in `domain/grade_class.py`.
1. Disk before API: detection workers never POST events; the line's outbox (`OutboxRetryWorker`, to the console) and `BatchUploadWorker` (R2) send them. `event_id` is always uuid5.
1b. The detection thread never waits for disk; PLC pulse, `processed` marks and the `timestamp` stay on the detection path.
1c. TP is paired to a bunch by distance, not by time order (`domain/garis_capture.tp_untuk_janjang`).
2. `_processed_objects`: never discard an active track (single trigger); trim only inactive and stale ids.
3. `state.lock` around every physical camera access.
4. MJPEG: only `DisplayWorker` writes `state.latest_frame`, via `Condition.notify_all()`.
5. DI: `lru_cache` singletons except capture/health services (camera injected at startup).
6. Lifespan, not `on_event`; `repo_root = parents[3]`; every worker `run_loop` wraps `run_once` in try/except.
7. `tp_status` is a boolean in the sidecar and `"PASS"`/`null` on the wire.
8. Encode or write failure raises `OSError` from `LocalFileStorage.write_image`; no orphan JSON.
9. Retention deletes all three WebP variants (`bbox/`, `clean/`, `thumb/`).
10. Console: `work_date` is computed at ingest and stored; the day starts at a support-set cutoff (default 00:00), never recomputed.
11. The console never scans directories; the screen reads only from `console.db`.
12. Sumber TBS: the edge mirrors AutoERP rules, never guesses.
13. Truck assignment: the line accepts first, then it is recorded; only Lepas paksa clears a line that gives no answer at all.
14. The console calls AutoERP; AutoERP never calls the factory.
15. Weighbridge: `net_kg` is computed, never trusted raw.
16. Manual trucks go up through the queue; AutoERP-owned trucks are read-only.
17. Recap: grading and weighing are two sources, only placed side by side.
18. Truck visit: one message, rebuilt every time, never patched (contract §4.C).
19. Console login: email + password, two account sources, verified offline; the session slides 12 h from the last touch, polls never renew it.
20. A QR scan carries the plate number and nothing else; one scan field records the truck's next step, decided on the server from its state, and shows only when support turns on the Scanner QR switch (default off).
21. Developer lane: the backend guards, the screen only tidies.
22. Licence: the factory verifies, AutoERP issues.
23. Developer video recording never slows grading.
24. PLC alarms: one ribbon for the whole screen, not per card.
25. Danger Zone: a line deletes its own data at boot; settings and licence survive.
26. History (Rekap tab): cross-day grading, read-only, on its own SQLite connection.
27. Last Sync: one section, two rows (AutoERP, Cloud Photo), for all operators.
28. Batch 1 factory-LAN security: audit holes closed without breaking an old `.env`.
29. Batch 2A: a line shuts down cleanly before exiting; evidence is written whole.
30. Console routes heavy on SQLite must not block the event loop.
31. Line to console queue: no give-up limit.
32. AI dead: one guard, three readers.
33. Logging: one install for lines and console, lines tagged with zone and line code, a fault logged once when it starts and once when it ends.
34. Line log and Discord: line warnings and errors reach the Log tab through a cursor pull; errors reach Discord as a digest, off while `DISCORD_WEBHOOK_URL` is empty.
35. Honest health and disk monitor: a connected camera that stops sending frames is a fault; free disk is watched on every line, with or without R2, and nothing is deleted; camera health without a temperature sensor is graded on the line (rate held low, frames lost, disconnects).
36. Automatic line assignment: one truck on the lines until weighed out; the next waits in the unloading queue; on by default on every line since 2026-10-05, support can turn it off.
37. Gate times (scan 1 arrive, scan 4 leave) stay on the factory PC and never go to AutoERP; scan 1 may be skipped; scan 4 before the weigh-out is refused; a cancelled arrival is kept as history; a weighed-out ticket with no scan 4 counts as finished after 24 h or when the truck returns, nothing written.
38. Update now: the console never touches Docker, it only writes a marker in `UPDATE_DIR` for the host watcher; refused while any truck is assigned.
39. Live scale: the console reads the weighbridge weight from a PLC word register on its own port and shows it; only the one scan field may save it as a ticket weight, and only when fit (stable, or the same kg for 2 s, at least 1,000 kg); a cut, stale or faulted reading shows a dash.

Conventions (full text in `docs/rules.md` § Conventions): process env vars beat `.env`
(`override=False`); three image sources (`CAMERA_TYPE` = `hikrobot` / `opencv` / `photo`,
video uses `opencv`); all paths via `Settings`, new env var gets a default in `core/config.py`;
ROI and the capture line are stored in **settings space** (`STREAM_WIDTH×STREAM_HEIGHT`, 1280×720) while the
stream picture keeps the camera's own ratio inside it (861×720 for 1224×1024, 2026-10-07); the capture line (`GARIS_CAPTURE`,
default 300, set from the console, `0` = off) decides **when** a bunch is photographed, ROI decides **where**;
no confidence number on bunch labels (`mode_dev` shows it); toasts close by themselves within
10 s; a restarted line is marked on its card; frame rate lives in `config/camera/hikrobot.mfs`;
`snake_case` files, `PascalCase` classes, `UPPER_SNAKE` env vars.

Git: default branch `staging`, PR-only, squash to `staging`, merge commit to `main` (so `main`
always has merge commits `staging` lacks; compare with `git diff --stat`, not `git cherry`).
CI green required by ruleset `ci-wajib-lolos` (id 24315701, `staging` and `main`): `lint-and-test`,
`browser (chromium)`, `browser (firefox)`; renaming a job or matrix entry locks every PR.
PR title `<type>(<scope>): ...`, PR body and **every commit message in English**, no em dash,
never a "Co-Authored-By: Claude" or other AI mention.

## 4. Never do

- Point `BACKEND_URL` at `api.smagri.id`: that flooded production with ~1,098 test events on 2026-08-09.
- Import torch or cv2 in `console_main.py`, in anything the console imports, or in tests.
- `make demo*` or `make reset-data-fresh` on the factory PC; `docker compose down -v` anywhere.
- Rename container names, the local image tag or the package (see §1).
- Use em dashes in screen text or any tracked markdown (`tests/unit/test_console_copy.py`,
  `tests/unit/test_dokumen_tanpa_em_dash.py`); in YAML frontmatter replace them with a comma, never a colon.
- Force-push, or commit with an AI mention or in Indonesian.
- Print `.env` or `media.env` secrets into a transcript.

## 5. Traps (dated; the expensive ones. More in `docs/rules.md` and the skills)

- A process env var beats `.env` and is visible only in `/health/detail`. Check the process env first.
- `media.env` must be passed with `--env-file`, not `env_file:`; with `env_file:` all three lines are `hikrobot` and nothing errors. `$(COMPOSE)` in the Makefile carries the flag.
- `load_dotenv()` climbs to the **first** `.env` it finds: in a worktree that is the main checkout's. `tests/conftest.py` cleans every `.env` on that path.
- 2026-09-20: a Compose override that names `environment:` **replaces** the base block on the factory PC (Compose 2.40.3); `docker compose config` on the Mac proves nothing. Skill `compose-host-pabrik`.
- `capture_save_dropped` > 0 in `/health/detail` = graded bunches with no image and no sidecar, no retry. Find the cause (slow disk, grading faster than writing).
- The feed URL in `kartuLine` must carry a unique `?t=` per render; a bare URL is served from the browser image cache with an old frame.
- `/ws/results` sends `image_url` before the file exists (hundreds of ms); nothing uses that lane today.
- TensorRT installs only from `pypi.nvidia.com`; the engine is hardware-locked and never committed; missing engine falls back to `.pt`.
- A horizontal capture line is scaled by frame **height**, not width (the 1224×1024 camera frame is not square; using width is ~19 % off with no error).
- Kiosk: `requestFullscreen()` needs a user gesture, so `scripts/console-kiosk.sh` does it (keep `--user-data-dir`, wait for the console to answer, `xset s off -dpms`).

## 6. When to read what

| Touching… | Read first |
|---|---|
| Any code, or reviewing it | `docs/coding-standard.md` (loaded above; cite its rule ids) |
| Any rule in §3, or something that "feels forbidden" | `docs/rules.md` (full text, rationale, dates) |
| A `make` target, tests, CI | `docs/commands.md`, `.github/workflows/ci.yml` |
| Flows, worker/state model, invariants, Docker/SDK/GPU internals, artifact layout, licence guard, console | `docs/overview.md` |
| Endpoints, event payload, env vars | `docs/backend-overview.md` |
| The console screen (`console.html`) or `/api/console/*` | skill `konsol-autograde` |
| A new env var, mount, port that the factory PC must receive | skill `compose-host-pabrik` |
| PLC, MC Protocol, coils, commissioning | `docs/plc-integration.md`, `docs/plc-mc-handoff.md`, skill `plc-mc-protocol` |
| Camera tuning (MVS), camera spec | skill `mvs-camera`, `docs/camera-spec.md` |
| The truck QR scanner (connecting, beeps, settings, Enter after a scan) | skill `scanner-qr` |
| Swapping or evaluating a detection model | skill `model-swap-eval`, `docs/runbooks/2026-09-24-model-deteksi-per-line.md` |
| Image source per line (video/photo) | `docs/runbooks/2026-09-21-sumber-kamera-per-line.md` |
| From-zero factory setup (NVIDIA, MVS, camera IP) | `docs/SETUP.md`; PC capacity: skill `spek-pc-pabrik` |
| Demo console on the droplet | `deploy/demo/`, `docs/runbooks/2026-09-28-konsol-demo-droplet.md` |
| Installing a factory PC, cutting a tag, deploying | skills `install-factory-pc`, `tag-release`, `deploy-production` in the `sawit` workspace |
| Being new here | `docs/MANUAL.md`, skill `panduan-autograde` |
| Reviewing a branch before a PR | `docs/REVIEW-CHECKLIST.md` (agent `rule-reviewer`) |

## 7. Final report (end every task with exactly this)

```
Changed:        files / behaviour
Validated:      command → result (paste the last lines)
Not validated:  what was not run and why
Risks:          what could still be wrong
Next:           the one thing to do next
```

## 8. Progress log

Before starting: skim the top 5 entries of `docs/PROGRESS.md`. After finishing: prepend your
final report there as a new entry (`## YYYY-MM-DD · <area> · <title> (PR #n)`).
