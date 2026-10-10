# AutoGrade

[![CI](https://github.com/delta-anugrah/autograde/actions/workflows/ci.yml/badge.svg?branch=staging)](https://github.com/delta-anugrah/autograde/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

AutoGrade grades fresh fruit bunches (FFB) at a palm oil mill in real time. Industrial cameras
watch the conveyor, a YOLO model classifies every bunch, a PLC fires the reject piston, and an
offline operator console records each truck visit and sends one summary per visit to AutoERP.

One Docker image runs four times on the factory PC:

| Container | Role | Port |
|---|---|---|
| `ripe_line_1`, `ripe_line_2`, `ripe_line_3` | One camera line each: capture, YOLOv8 + ByteTrack, PLC pulse, evidence on disk | 8001, 8002, 8003 |
| `palmgrade_console` | Operator console (`APP_MODE=console`): grading, trucks, weighbridge, recap; talks to AutoERP | 8100 on the factory PC, 8000 in the dev compose |

The console never imports torch or OpenCV, so a dead camera line cannot take the operator screen
down, and it keeps working with the internet down.

New to the project? Start with [`docs/MANUAL.md`](docs/MANUAL.md) (Indonesian, printed version
`docs/MANUAL.pdf`): what the system does, how the console is used, installation, operations, the
folder map (§9.1) and first steps (§9.2).

## Contents

- [System context](#system-context)
- [How it works](#how-it-works)
- [Grading rules](#grading-rules)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Running](#running)
- [Operator console](#operator-console)
- [Camera sources](#camera-sources)
- [HTTP API](#http-api)
- [Evidence, upload and storage](#evidence-upload-and-storage)
- [Per-truck grading detail (R2)](#per-truck-grading-detail-r2)
- [Licence guard](#licence-guard)
- [Testing](#testing)
- [Release and deployment](#release-and-deployment)
- [Contributing](#contributing)
- [Documentation map](#documentation-map)
- [License](#license)

## System context

| Component | Role |
|---|---|
| **AutoGrade** (this repo) | Factory PC: three camera lines and the operator console. Works offline. |
| **AutoERP** (`delta-anugrah/autoerp`) | ERPNext fork with the `palm_mill` module. Receives one message per truck visit, issues licences, holds master data (suppliers, trucks, operator accounts). |
| `palmgrade-api`, `palmgrade-frontend` | Retired on 2026-09-20. The console replaced them on the factory PC. |

The lines post their events to the local console (`BACKEND_URL`), with the same contract the old
API used, so the line code did not change when the console took over. The console calls
AutoERP; AutoERP never calls the factory.

## How it works

### Camera line

```
Camera (Hikrobot GigE / OpenCV webcam or video / still photo)
  -> FrameCaptureWorker (thread) -> frame_queue
  -> FrameProcessingWorker (thread)
       YOLOv8 + ByteTrack -> Ripe / Unripe / JK (empty bunch) / TP (long stalk)
       bunch touches the capture line -> PLC pulse + hand a SaveJob over, then continue
  -> CaptureSaveWorker (thread, queue of 8)
       encode WebP (bbox, clean, thumb), write the JSON sidecar, add one outbox row
  -> OutboxRetryWorker (polls every 1 s) -> POST BACKEND_URL (the local console)
  -> BatchUploadWorker (hourly, separate path)
       scan -> UploadManifest (state/upload_manifest.db) -> PUT images to Cloudflare R2
       -> optional text POST to UPLOAD_API_URL (empty at the factory)
       -> retention: delete uploaded files older than UPLOAD_RETENTION_DAYS
  -> StreamingService -> MJPEG /api/video_feed (many viewers, one Condition broadcast)

console -> POST /internal/assignment     (which truck is on this line)
console -> POST /internal/manual-reject  (operator reject)
```

The detection thread never waits for disk or network: evidence is written first, then workers
deliver it. Full flow and invariants: [`docs/overview.md`](docs/overview.md) §2 to §6.

### Operator console

```
3 lines            -> POST /api/v1/internal/vision/events -+
weighbridge program -> POST .../scale/weighing             +-> SQLite index state/console.db
                                                           |   (the console never scans folders)
                                                           +-> MasterDataWorker  <- suppliers, trucks, accounts from AutoERP
                                                               ErpOutboxWorker   -> new trucks (§4.B) and truck visits (§4.C)
                                                               VisitResendWorker -> yesterday's visits, once a day
PLC word register (MC Protocol, port 1028) -> TimbanganLiveWorker -> live scale tile (when SCALE_PLC_REGISTER is set)

/console -> one static HTML file, vanilla JS, no build step, no CDN
            camera streams are <img> MJPEG straight from :8001/:8002/:8003, not through the console
```

## Grading rules

The model (`models/release/best.pt`) has four classes. A class is not a verdict: the verdict is
derived from the class in `src/palmgrade/domain/grade_class.py`. The binary `ripeness_status`
drives the piston and is what gets booked; `grade_class` is the four-way detail on screen.

| Model class | Verdict | PLC coil | Piston |
|---|---|---|---|
| `Ripe` | ACC | `PLC_COIL_BASE + 0` | no |
| `Unripe` | REJ | `PLC_COIL_BASE + 1` | yes |
| `JK` (empty bunch) | REJ | `PLC_COIL_BASE + 1` | yes |
| `TP` (long stalk) | none | no pulse | no |

- `PLC_COIL_BASE` per line: line 1 = M1000, line 2 = M1003, line 3 = M1006 (MC Protocol; map in
  [`docs/plc-mc-handoff.md`](docs/plc-mc-handoff.md)). `Unripe` and `JK` share a coil because the
  panel has two outputs per camera.
- REJ bunches from an **Internal** truck are not pulsed (`src/palmgrade/domain/plc_signal.py`):
  they go to the ramp anyway, so the PLC's NG counter is lower than the console's REJ count while
  an internal truck unloads.
- **Minimum size:** boxes smaller than `MINIMUM_SIZE` (460,000 px²) are forced to REJ.
- **Tracking:** ByteTrack gives each bunch a `track_id`; a bunch is saved once (single trigger).
- **Detection zone:** only boxes whose centre falls in the ROI (`ROI_X1/Y1/X2/Y2`, default the full
  frame) count. The ROI set in the console's Setelan tab wins over `.env`. TP is exempt.
- **When to photograph:** a bunch is captured when its box **touches** the capture line
  (`GARIS_CAPTURE`, set from the console, `0` = off). The ROI says *where*, the line says *when*.
  `SUMBU_GARIS` picks a vertical line (horizontal conveyor, px from the left) or a horizontal one
  (px from the top).
- **Long stalks:** a TP is paired with the nearest bunch within 1.5 times half its box diagonal,
  and only if no other bunch in that frame is closer (`domain/garis_capture.tp_untuk_janjang`).
  A TP that arrives late is counted in `tp_telat` on `/health/detail`.
- **Overlapping bunches:** more than one unprocessed bunch in the ROI in the same frame forces all
  of them to REJ.
- **Labels:** boxes show the class only, no confidence percentage (from a few metres "54%" reads
  like a ripeness level). The `mode_dev` switch in Setelan brings the number back for tuning.

Rule texts with rationale: [`docs/rules.md`](docs/rules.md) (rules 0, 1c and 2).

## Quick start

Two paths, kept separate on purpose. Production always runs on Linux; development may run on a
Mac. The Linux path is never changed for the Mac's sake.

| | Develop on a Mac (no camera) | Linux / factory PC (production) |
|---|---|---|
| Runs | Operator console, native (no Docker) | Three camera lines and the console, in Docker |
| Needs | Python 3.12 | Docker, an NVIDIA GPU with the Container Toolkit, Hikrobot MVS SDK in `/opt/MVS`, a `.pt` model |
| Start | `make console` | `make up` from source, or the `autograde` launcher with the GHCR image (factory PCs) |
| Screen | <http://127.0.0.1:8100/console> | <http://localhost:8000/console> from source, `:8100` with the production image |

### Develop on a Mac

```bash
git clone git@github.com:delta-anugrah/autograde.git
cd autograde
cp .env.example .env

# A small venv for the console and the tests. It deliberately leaves out torch, ultralytics and
# OpenCV: the console does not use them, and requirements.txt is for the Docker image.
# segno (pure Python) renders the truck QR cards on the server, so console.html needs no CDN.
python3.12 -m venv .venv
.venv/bin/pip install "fastapi==0.115.12" "uvicorn[standard]==0.34.0" "python-dotenv==1.1.0" \
  "httpx==0.28.1" "pydantic==2.11.3" "segno==1.6.6" \
  pytest ruff cryptography aiosqlite psutil boto3 pyyaml

make operator        # once: a local account to sign in with (asks for email, name, password)
make demo            # optional: fill the screen with sample data (see "Demo data")
make console         # http://127.0.0.1:8100/console, Ctrl-C to stop
.venv/bin/pytest tests/unit
```

- Without AutoERP the console runs fully from local data (`ERP_URL` empty). The three camera cards
  show **OFFLINE**: correct, there are no camera lines on a Mac.
- Port **8100**, not 8000: a local AutoERP bench uses 8000.
- `make up` and `make up-prod` stop at `Hikrobot MVS SDK not found at /opt/MVS` on a Mac, as
  intended. `make up-dev` builds on Apple Silicon, but its console uses `network_mode: host` on
  port 8000 (taken by AutoERP) and its lines have no camera.

### Linux / factory PC

Prepare the machine with [Configuration](#configuration) and [`docs/SETUP.md`](docs/SETUP.md),
then `make up` (all targets in [Running](#running)). Factory PCs do not run `make`; see
[Release and deployment](#release-and-deployment).

## Configuration

```bash
cp .env.example .env              # line, console, PLC, R2, AutoERP, licence
cp media.env.example media.env    # camera source and model per line (written later by the console)
mkdir -p models/release           # put best.pt here (not in git)
```

Key settings in `.env`:

```env
# Where the lines send their events: the local console.
#   inside Docker: http://console:8000    native `make line`: http://localhost:8100
BACKEND_URL=http://localhost:8100
# Shared secret line <-> console and the weighbridge program. Must not stay on the default:
# with APP_ENV=production the lines and the console refuse to boot on a public default.
WEBHOOK_SECRET=change-me
# Key for console -> line commands (restart, delete data, PLC coils, piston). Empty = falls back
# to WEBHOOK_SECRET, so an old .env keeps working.
INTERNAL_SECRET=
# One id per line; the console maps events to lines by machine_id. The compose files carry defaults.
LINE_1_MACHINE_ID=<uuid>
LINE_2_MACHINE_ID=<uuid>
LINE_3_MACHINE_ID=<uuid>
# Detection
MODEL_FILE=best.pt
CONF_THRESHOLD=0.75
MINIMUM_SIZE=460000
# MJPEG stream box. The picture keeps the camera's aspect ratio inside it; also the grid for the
# ROI and the capture line. Does not change what is saved.
STREAM_WIDTH=1280
STREAM_HEIGHT=720
```

- A process environment variable beats `.env` (`override=False`). Check the process env first when
  a setting "does not apply"; the effective values are on `/health/detail`.
- `media.env` must reach Docker with `--env-file`, not `env_file:` (the Makefile does this).
- Every variable with its default, including the ones that look unused but are not:
  [`docs/backend-overview.md`](docs/backend-overview.md) § Environment Variables.

## Running

Everything goes through `make` from the repo root. Full list with flags:
[`docs/commands.md`](docs/commands.md).

| Target | What it does |
|---|---|
| `make up` | Production build from source: copy the SDK from `/opt/MVS`, build GPU + SDK, start every line |
| `make up-dev` | Development: CPU build without the SDK, start every line |
| `make start` / `make restart` | Start without rebuilding / restart (enough for a code change: the source is bind-mounted) |
| `make up-1`, `make up-2`, `make up-3` | Start one line without rebuilding |
| `make down`, `make ps` | Stop everything / container status |
| `make logs`, `make logs-1` ... `make logs-3` | Follow the logs of all lines or one line |
| `make up-console`, `make logs-console`, `make restart-console` | The console container only (port 8000), safe to restart without touching the lines |
| `make console` | The console natively on `127.0.0.1:8100` (Mac development) |
| `make kiosk` | Open the console full screen on this PC (`scripts/console-kiosk.sh`) |
| `make rebuild`, `make rebuild-clean` | Rebuild the GPU image / rebuild without cache (slow; only if the cache is suspect) |
| `make build-engine` | Build the TensorRT FP16 engine, once per GPU; skipped when it exists |
| `make reset-data` | Show what would be deleted (photos and databases) |
| `make reset-data-fresh` | **Delete** `artifacts/` and `state/` (asks you to type HAPUS) |

| Container | Port | Camera index | Machine id |
|---|---|---|---|
| `ripe_line_1` | 8001 | 0 | `LINE_1_MACHINE_ID` |
| `ripe_line_2` | 8002 | 1 | `LINE_2_MACHINE_ID` |
| `ripe_line_3` | 8003 | 2 | `LINE_3_MACHINE_ID` |
| `palmgrade_console` | 8000 (dev), 8100 (prod) | none | all three (maps `machine_id` to a line) |

> [!WARNING]
> `make reset-data-fresh` cannot be undone and makes no backup. It deletes every photo and sidecar
> (`artifacts/`) and every SQLite file (`state/`): grading history, trucks, weighings, unsent
> queues and accounts made with `make operator`. The two built-in image accounts are recreated at
> the next console start. Never run it on a factory PC in production. Without a terminal, the
> console's Danger Zone (support account, Setelan tab) deletes data more carefully: it keeps the
> grading settings and the licence, and refuses while a line is down, a truck is assigned or a
> queue is unsent.

- **One image, three line containers.** Only `line-1` has a `build:` block; lines 2 and 3 reuse
  `palmgrade-vision:latest`. `make rebuild` then `make start` updates all three.
- **Code reload.** The source is mounted at `/app`; with `APP_ENV=development` Python changes reload
  without a rebuild. In production `make restart` is enough for code; rebuild only when
  dependencies, the `Dockerfile` or the SDK change.
- **TensorRT.** The FP16 engine (`engines/<model>.sm<cc>.engine`) is locked to the GPU and the
  TensorRT version, so it is never committed or baked into the image. A missing or mismatched
  engine falls back to the `.pt` model (`pipelines/model_registry.py`): same accuracy, slower.
  TensorRT installs only from `pypi.nvidia.com`; the public PyPI package is a stub that hangs pip.

## Operator console

The screen is `/console`: one static HTML file (`src/palmgrade/static/console.html`), vanilla JS,
no build step, no Node, no CDN, zero `https://` references, so it opens with the internet down.
Its two fonts (Plus Jakarta Sans, Barlow Condensed) and the sign-in photos are embedded
(`scripts/tanam_font.py`, `scripts/tanam_foto_masuk.py`).

- **Layout.** A collapsible menu on the left; a header with the **Last Sync** pills (AutoERP and
  Cloud Photo); a day summary (bunches, live scale, trucks on the lines, unloading queue); one
  card per camera line (live stream, latest photos, manual reject, piston, a menu to assign or
  release a truck).
- **Tabs.** Operators see Grading, Truk, Timbangan and Rekap. Support accounts also see Log,
  Status, Akun, Line and Setelan. Indonesian and English, light (default) and dark theme; the
  choices live in `localStorage`.
- **Sign-in.** Email and password. Every `/api/console/*` call answers 401 without the
  `konsol_sesi` cookie, except the page itself, the account list and `login`. A session ends 12 h
  after the screen was last touched (polls do not extend it). Manual rejects are recorded under the
  signed-in name.
- **Accounts.** Two sources, both verified on the factory PC, so sign-in works offline: AutoERP
  (DocType `AutoGrade Operator`, pulled with the master data, hashes only) and **local** accounts on
  this PC. Every image carries two built-in accounts, `operator@autograde.local` and
  `support@autograde.local`, whose password hashes are set per mill at install
  (`make hash-sandi` -> `CONSOLE_DEFAULT_HASH`, `CONSOLE_SUPPORT_HASH`). They are created only when
  missing, so a changed password survives a restart. Local accounts are managed in the Akun tab
  (support) or with `make operator` / `make operator-docker`; AutoERP accounts are reset in AutoERP.
- **Camera streams** go straight to the lines. Cards are drawn once and patched every 2 s (moving
  DOM nodes would reopen the streams). Camera status shows as **ONLINE / OFFLINE** in words, never
  colour alone.
- **Manual reject without a mouse:** hold `Space`, then press `1`, `2` or `3`.
- **Rekap** is what the supplier receives: one row per truck (bunches, Ripe/Unripe/JK/TP, ratio,
  net weight), today or up to 31 days back, with CSV download. Grading and weighing stay two
  sources placed side by side (rule 17). Bunches graded before a truck was assigned show as
  **Tanpa truk** (no truck) rather than being dropped. Support accounts can import a CSV from another
  PC, all or nothing, and undo an import (rule 26).
- **Full screen** is the browser's job: `make kiosk` runs the browser in kiosk mode through
  `scripts/console-kiosk.sh`, and `scripts/palmgrade-console.desktop` starts it at login.

> [!IMPORTANT]
> Installing AutoGrade on a PC that already ran `palmgrade-api` needs `make rekonsiliasi-truk`
> (OPS-2) **before** `ERP_URL` is set. Old truck ids were random, AutoGrade derives ids from the
> plate, and the plate column has no unique index: without it the first pull splits one truck's
> tonnage over two rows, silently. A new PC with an empty database does not need it.

### Demo data

```bash
make demo           # 10 trucks, about 6 visits a day for a week, two accounts
make demo HARI=3    # a shorter history
make demo-reset     # delete the demo data, then seed again
make demo-off       # after a showcase: delete the demo data and stop there
make console        # http://127.0.0.1:8100/console
```

Sign in as `operator@demo.autoerp.test` or `support@demo.autoerp.test`, password `sawit2026`.
With the console in Docker use `make demo-docker`. **Never on a factory PC:** the seeder writes to
the operator's database (it refuses one with real data, but do not rely on that). The plates match
the AutoERP seeder (`erpnext/palm_mill/demo.py`) so one truck is the same truck on both screens;
change a plate on one side and change it on the other in the same PR. Ids are deterministic
(uuid5), so seeding twice adds nothing.

For a moving screen (camera frames, counters, a scale that rises and falls) like
`demo-autograde.smagri.id`: `DEMO_MODE=1 make console`. The simulation runs in the browser only and
writes nothing; the console refuses to boot with `DEMO_MODE` next to a PLC or scale setting
([runbook](docs/runbooks/2026-09-28-konsol-demo-droplet.md) § Mode demo hidup).

After seeding, `CONSOLE_EMAIL=operator@demo.autoerp.test CONSOLE_SANDI=sawit2026 scripts/smoke-console.sh`
checks the session lock, calls every endpoint the screen uses, confirms the page served is the one
in the working tree, and checks three past traps (the "Tanpa truk" row, net weight of a truck with
two tickets summed rather than multiplied, `bruto_kg` "14.820" refused). It must report zero FAIL.

A `console.html` change needs only a browser refresh (the file is bind-mounted). A Python change
needs `make restart-console`; `make up-console` is not enough, because `up -d` does nothing while
the container runs.

### Connecting to a local AutoERP

```bash
cd ../autoerp && make up && make key-show   # paste ERP_API_KEY and ERP_API_SECRET into .env
cd ../autograde && make console             # native uvicorn on 127.0.0.1:8100
```

Set `ERP_URL=http://pks.localhost:8000`, `ERP_API_KEY`, `ERP_API_SECRET`, `ERP_COMPANY` and
`CONSOLE_LINE_HOST=http://127.0.0.1` in `.env` (on macOS `localhost` resolves to `::1` first, the
lines listen on IPv4 only). `make console` sets `WEBHOOK_SECRET=devsecret`, which beats `.env`.
Do not run `create_integration_user` again to read a key: it rotates the secret.

End-to-end tests against a real AutoERP (11 tests, they clean up after themselves; they need port
8001 free and one operator account):

```bash
E2E_CONSOLE_URL=http://127.0.0.1:8100 E2E_WEBHOOK_SECRET=devsecret \
E2E_EMAIL=operator@pks.test E2E_SANDI=<password> \
E2E_ERP_URL=http://pks.localhost:8000 E2E_ERP_API_KEY=<key> E2E_ERP_API_SECRET=<secret> \
E2E_ERP_ADMIN_PASSWORD=admin .venv/bin/pytest tests/e2e -v
```

## Camera sources

The source is chosen per line from the console (Line tab, Sumber Kamera, support only), stored in
`media.env` and read by the line at boot. No code change is needed to switch.

| `CAMERA_TYPE` | Source | Selected by |
|---|---|---|
| `hikrobot` | Hikrobot industrial camera over Ethernet (GigE Vision) | `CAMERA_SERIAL`, then `CAMERA_DEVICE_INDEX` |
| `opencv` | Webcam or video file | `MEDIA_FILE` or `CAMERA_VIDEO_PATH` for a file, else `CAMERA_DEVICE_INDEX` |
| `photo` | A still image, looped | `MEDIA_FILE` or `CAMERA_PHOTO_PATH` |

- GigE cameras need `network_mode: host` (set in the compose files) so the container can discover
  them by UDP broadcast; camera and host must share a subnet.
- A line starts without a camera: `/health/detail` reports `camera_connected: false` and
  `FrameCaptureWorker` retries until the camera appears, no restart needed.
- The MJPEG stream fits the picture into the `STREAM_WIDTH` x `STREAM_HEIGHT` box at the camera's
  own aspect ratio (861 x 720 for a 1224 x 1024 camera). Saved photos keep the full resolution.

Camera tuning and network: [`docs/camera-spec.md`](docs/camera-spec.md),
[`docs/runbooks/2026-09-21-sumber-kamera-per-line.md`](docs/runbooks/2026-09-21-sumber-kamera-per-line.md).

## HTTP API

The complete, current list of line and console endpoints, payloads and environment variables is in
[`docs/backend-overview.md`](docs/backend-overview.md) § HTTP Surface. Every `/api/console/*` route
needs a session; the support routes `/api/console/dev/*` need the `support` role.

```bash
# Line
curl http://localhost:8001/health          # 200 healthy; 503 when the AI is dead or a connected camera stops sending frames
curl http://localhost:8001/health/detail   # always 200; capture_save_dropped and tp_telat must be 0

# Console (8100: production image and `make console`; 8000: dev compose)
curl -s -c /tmp/console.jar -H 'content-type: application/json' \
  -d '{"email":"operator@pks.test","sandi":"<password>"}' http://localhost:8100/api/console/login
curl -b /tmp/console.jar http://localhost:8100/api/console/state
```

- **Logs** carry the factory time zone (`FACTORY_TZ`) and the line code or `console` on every line.
  Line warnings and errors are also stored in `state/line-N/log_line.db` and pulled into the
  console's Log tab, so they survive a recreated container. Errors can be sent to Discord as a
  digest when `DISCORD_WEBHOOK_URL` is set (rules 33 to 35).
- **Weighbridge:** `neto_kg` is computed, never trusted (more than 1 kg off `bruto - tara` is
  refused with 400), and the 1-tonne minimum catches a thousands separator read as a decimal
  (`14.820` as 14.82 kg). Rules 15 and 20.

## Evidence, upload and storage

Every graded bunch is written to disk first. Two paths deliver it, independently:

1. **Realtime to the console:** one outbox row per bunch in `state/line-N/outbox.db`, sent by
   `OutboxRetryWorker` (1 s poll, backoff from 5 s to 10 min per row, never gives up).
2. **Hourly to Cloudflare R2:** `BatchUploadWorker` scans the result folders, records each item in
   `state/upload_manifest.db` (`pending` -> `image_uploaded` -> `done`, or `poisoned`), and PUTs the
   images. Retries never give up; only the backoff grows.

```
artifacts/line-1/results/2026-05-18/                     date folder (UTC)
  2026-05-18_103000_auto_ripeness.json                   sidecar, FLAT in the date folder
  2026-05-18_103000_auto_tp.json                         long stalk, when detected
  083000_B1234XY_a3f9c201/                               one folder per truck visit (factory time)
    bbox/{acc,rej}/2026-05-18_103000_auto.webp            with boxes; uploaded to R2
    clean/{acc,rej}/2026-05-18_103000_auto.webp           without boxes; for retraining, never uploaded
    thumb/{acc,rej}/2026-05-18_103000_auto.webp           400 px; uploaded to R2 for the viewer
  _belum-assign/                                         graded before a truck was assigned

state/line-1/                                            outside the static /captures mount
  upload_manifest.db   outbox.db   license.db   log_line.db
```

> [!WARNING]
> - **Sidecars must stay flat in the date folder.** The uploader finds them with
>   `glob("*/*_ripeness.json")`; a sidecar in a subfolder is never found and uploads stop with no
>   error and no log. Only images move into subfolders; the uploader reads their place from
>   `image_path` in the JSON.
> - **Truck folders use `FACTORY_TZ`, file names stay UTC.** File names derive the uuid5
>   `event_id` and must not shift; the folder name is the one place a person reads the time
>   (`domain/capture_layout.py`, written by `services/capture_writer.py`).
> - **`results/` is not an archive.** Retention deletes `done` items older than
>   `UPLOAD_RETENTION_DAYS` (default 7), all three variants together; after that the only copy is in
>   R2. `poisoned` items are kept for inspection. With `R2_BUCKET` empty, retention does not run
>   at all, so nothing cleans the disk; the per-line disk monitor (`DISK_PERINGATAN_GB` 15,
>   `DISK_KRITIS_GB` 5) warns on the console but deletes nothing.

Since 2026-09-28 `outbox.db` and `license.db` live in `state/`, not `artifacts/` (they used to be
reachable through the `/captures` mount). An upgraded PC absorbs the old files at first boot
(`services/pindah_db_line.py`); a failed absorb is reported on `/health/detail`
(`outbox_lama_tertinggal: true`) and blocks Danger Zone deletes until it succeeds.

Photos are served as static files at
`GET /captures/results/{date}/{HHMMSS}_{plate}_{assign8}/{bbox|clean|thumb}/{acc|rej}/{file}`.

### Text upload payload (only when `UPLOAD_API_URL` is set)

At the factory `UPLOAD_API_URL` is empty: the image in R2 is the upload, an item is `done` as soon
as its image PUT succeeds, and the POST below never happens. When it is set, each item is posted
after its image:

```json
{
  "event_id": "uuid",
  "assignment_id": "uuid",
  "machine_id": "uuid",
  "truck_id": "uuid-or-null",
  "timestamp": "2026-05-18T10:30:00.123456+00:00",
  "image_path": "https://captures.smagri.id/<machine_id>/2026-05-18/083000_B1234XY_a3f9c201/bbox/rej/2026-05-18_103000_123456_auto.webp",
  "prediction": "Acc",
  "ripeness_status": "ACC",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS",
  "tp_confidence": 0.88,
  "capture_type": "auto",
  "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
}
```

- `event_id`: uuid5 of `machine_id:timestamp` for automatic captures, so a re-upload is answered
  `already_processed`; uuid4 for manual rejects.
- `assignment_id` is omitted, not `null`, when the capture had no assignment.
- `image_path` is the absolute R2 URL; the image is PUT before the POST.
- `timestamp` is ISO-8601 in UTC with an offset.
- `ripeness_status` is `ACC` or `REJ`; `tp_status` is `PASS` or `null`, never `"TP"` (rule 7).
- `truck_id` may be `null`: events without an active truck are uploaded too.

## Per-truck grading detail (R2)

Each truck released from a line gets one detail page that the office can open from the AutoERP
ticket. The factory PC accepts no inbound connections, so the page lives in R2 next to the
photos (`captures.smagri.id`, behind a password gate since 2026-09-24).

1. When a truck is released (or once all its lines are released, at the empty weighing), the
   console builds **one JSON per visit** from its own database (`domain/visit_manifest.py`, pure)
   at key `visits/<visit_id>.json`. `visit_id` is the `weighings` row id, the same number as
   `autograde_visit_id` on the ERP ticket.
2. The JSON goes through its own queue (`workers/visit_manifest_worker.py`, database
   `manifest_outbox.db`), so a dead R2 never holds back AutoERP and the reverse. The worker also
   uploads `static/viewer.html` once per process, so viewer and manifests never drift.
3. `detail_url` = `{R2_PUBLIC_URL}/viewer.html?visit=<visit_id>` is deterministic and is sent to
   AutoERP without waiting for the upload; photos not yet uploaded show as such in the viewer.
4. `static/viewer.html` has zero external dependencies, reads its manifest by relative path and
   shows a photo grid with filters (All, ACC, REJ, Long stalk).

`detail_url` is sent only when R2 is configured. Without R2 the key is **absent**, not an empty
string: each message to AutoERP replaces the parts it carries, so an empty string would erase a URL
AutoERP already has (`domain/erp_messages.py`). The Status tab shows this queue as **Manifest R2**,
reading "not active" rather than zero while R2 is not set. Setup and rollout:
`sawit/docs/runbooks/2026-09-16-rencana-detail-grading-r2.md`.

## Licence guard

Off by default (`LICENSE_ENABLED=false`).

```env
LICENSE_ENABLED=true
LICENSE_PUBLIC_KEY=-----BEGIN PUBLIC KEY-----\nMCow...\n-----END PUBLIC KEY-----
LICENSE_TOKEN=<token issued in AutoERP>
```

Tokens are Ed25519-signed and issued in AutoERP (DocType `AutoGrade Licence`, Administrator only);
the factory only verifies them, offline (rule 22). On a factory PC a new token is installed with
the launcher, `palmgrade license <token>`. With an expired licence every route except `/health`,
`/api/video_feed` and `/captures` is blocked, `FrameProcessingWorker` stops inference, and the
PLC alive coil drops, so an expired subscription is visible on the floor. Details:
[`docs/overview.md`](docs/overview.md) §10.

## Testing

Unit tests are pure logic: no torch, OpenCV, camera SDK or GPU, so they run on a plain CI runner.
`tests/integration/` wires real components without hardware (console and lines over an ASGI
transport, files in a temporary folder, screen rendering through node). `tests/browser/` drives the
real console in Firefox and Chromium with Playwright.

```bash
pip install -r requirements-ci.txt     # pinned, same versions as requirements.txt
ruff check src/ tests/
python tests/cek_skrip_konsol.py src/palmgrade/static/console.html   # every <script> block parses
pytest tests/unit tests/e2e tests/integration -rs
make test-browser                      # once per machine: make browser-siap
```

CI (`.github/workflows/ci.yml`) runs all of the above on every PR to `staging` and `main`. The
ruleset `ci-wajib-lolos` requires the jobs `lint-and-test`, `browser (chromium)` and
`browser (firefox)`; renaming a job or a matrix entry locks every PR. pytest settings are in
`pyproject.toml` (`pythonpath = ["src"]`); async code is tested with `asyncio.run`, without
`pytest-asyncio`.

| Area | Main tests | What they lock |
|---|---|---|
| Batch upload | `test_batch_upload_worker.py`, `test_upload_manifest.py`, `test_r2_uploader.py`, `test_batch_upload_outage.py`, `test_batch_upload_crash.py` | Any outage length: no data lost, no duplicates; a crash mid-transition leaves the manifest consistent |
| Line shutdown | `test_penutup_line.py`, `test_capture_save_kuras.py`, `test_berkas_utuh.py`, `test_tulis_atomik.py` | One bounded shutdown order; a power cut never leaves a 0-byte file with a valid name |
| Idempotency and time | `test_event_id.py`, `test_capture_timestamp.py` | Deterministic uuid5 ids; timezone-aware timestamps |
| Realtime outbox | `test_outbox_store.py`, `test_outbox_retry_worker.py`, `test_kirim_antrean_line.py` | Per-row backoff, no give-up limit, immediate flush on reconnect |
| Console | `test_console_store.py`, `test_working_day.py`, `test_console_html*.py` | SQLite index, working day across midnight, screen invariants |
| Weighbridge | `test_weighing.py`, `test_timbangan_live_domain.py`, `plc/test_pembaca_timbangan.py` | Computed net weight, merged empty weighing, live scale reading |
| AutoERP | `test_erp_master_data.py`, `test_erp_outbox_worker.py`, `test_visit_message.py`, `test_visit_resend.py` | Exact DocType fields, rejected vs unreachable, contract §4.B and §4.C |
| Per-truck detail | `test_visit_manifest.py`, `test_visit_manifest_worker.py`, `test_viewer_html.py` | Manifest shape, its own queue, a viewer without external dependencies |
| PLC | `tests/unit/plc/`, `tests/e2e/test_mc_protocol_lane.py` | MC Protocol and Modbus clients, pulse and heartbeat state machine |
| Licence | `test_license_manager.py`, `test_license_local_repo.py` | Real Ed25519 verification, state machine, anti-rollback |
| CI and release | `test_ci_gerbang_rilis.py`, `test_rilis_lewat_smoke.py`, `test_demo_image_workflow.py`, `tests/integration/test_alur_rilis_integrasi.py` | Images build only after CI passes on the tagged commit; release tags only after the image smoke test |
| End to end | `tests/e2e/test_console_autoerp.py` | Console and a real AutoERP; skipped without the `E2E_*` variables |

New logic gets a failing pure-logic test first; hardware never enters CI
([`docs/coding-standard.md`](docs/coding-standard.md) T1 to T4).

## Release and deployment

- **Image:** `ghcr.io/delta-anugrah/autograde` (one name; pinned by
  `tests/unit/test_deploy_image_name.py`). Container names, the local tag `palmgrade-vision:latest`
  and the package `src/palmgrade/` never change: renaming them breaks installed factory PCs.
- **Release:** a `vX.Y.Z` tag on `main` runs `.github/workflows/deploy.yml`: CI on the tagged commit,
  then the factory image (GPU, CUDA, camera SDK) and the demo image `vX.Y.Z-cpu` are built as
  candidates, smoke-tested (`scripts/smoke_image.py`) and only then promoted. The factory image
  also gets `latest`; the demo image never does.
- **Factory PCs do not build or run `make`.** They run the GHCR image through the launcher in
  `/opt/palmgrade/` with three compose files that live on the host. `:latest` is downloaded after a
  healthy start and installed at the next start, or at once with **Update now** in the Status tab.
  A version that fails its health check at start is rolled back by the launcher. Install steps:
  [`docs/SETUP.md`](docs/SETUP.md), [`docs/MANUAL.md`](docs/MANUAL.md) §5, and the
  `install-factory-pc` skill in the sawit workspace.
- **Demo:** `demo-autograde.smagri.id` is upgraded by the job `deploy-demo` after both images of a
  tag are released ([runbook](docs/runbooks/2026-09-28-konsol-demo-droplet.md) § Upgrade otomatis).

> [!WARNING]
> On the factory PC the console listens on **8100**, not 8000 (`docker-compose.prod.yml`), because
> 8000 is the Frappe bench port. A compose override that names `environment:` **replaces** the base
> block instead of merging with it (proven on Compose 2.40.3 at the factory; Compose 5.x on a Mac
> merges and proves nothing), which is why the console block in `prod` is written out in full. A
> new setting the factory must receive goes through the `compose-host-pabrik` skill.

## Contributing

- Default branch `staging`. Branch from `staging`, open a PR, **squash-merge** into `staging`.
  Releases are a PR `staging` -> `main` merged with a **merge commit**. Compare the two branches
  with `git diff --stat origin/staging origin/main` (empty = no difference), not `git cherry`.
- Direct pushes to `staging` and `main` are blocked; CI must pass.
- PR titles `<type>(<scope>): ...`; titles, bodies and commit messages in English; no em dashes; no
  AI attribution lines in commits.
- Read [`docs/coding-standard.md`](docs/coding-standard.md) before writing code and
  [`docs/REVIEW-CHECKLIST.md`](docs/REVIEW-CHECKLIST.md) before opening a PR. A behaviour change
  updates its doc in the same PR, and every task adds its report to
  [`docs/PROGRESS.md`](docs/PROGRESS.md).

## Documentation map

| Topic | Read |
|---|---|
| The system for a newcomer, operating the console (Indonesian) | [`docs/MANUAL.md`](docs/MANUAL.md) |
| Architecture, workers, invariants, artifact layout, console internals | [`docs/overview.md`](docs/overview.md) |
| Endpoints, payloads, every environment variable | [`docs/backend-overview.md`](docs/backend-overview.md) |
| The numbered rules and their reasons | [`docs/rules.md`](docs/rules.md) |
| Coding standard | [`docs/coding-standard.md`](docs/coding-standard.md) |
| Every `make` target, tests, CI | [`docs/commands.md`](docs/commands.md) |
| Installing a machine (NVIDIA, MVS SDK, camera IPs) | [`docs/SETUP.md`](docs/SETUP.md) |
| PLC integration and commissioning | [`docs/plc-integration.md`](docs/plc-integration.md), [`docs/plc-mc-handoff.md`](docs/plc-mc-handoff.md) |
| Camera hardware and tuning | [`docs/camera-spec.md`](docs/camera-spec.md) |
| Operational runbooks | [`docs/runbooks/`](docs/runbooks/) |
| Change log, newest first | [`docs/PROGRESS.md`](docs/PROGRESS.md) |
| Rules for AI agents working in this repo | [`CLAUDE.md`](CLAUDE.md) |

## License

[MIT](LICENSE).
