# CLAUDE.md — palmgrade-vision

> **This is the MAP, not the manual.** It tells you *where to look*. For deep flows,
> diagrams, full invariants, worker/state model, and Docker/SDK internals, read
> **`docs/overview.md`** (on-demand, not auto-loaded).
> `AGENTS.md` is a symlink to this file (Codex/Copilot read the same map).

---

## System Role

`palmgrade-vision` is the **Python AI camera service**. It runs as **3 Docker containers**
(one per camera line), each doing real-time YOLO ripeness detection on its own port and
delivering detection events to `palmgrade-api`. One of three repos:

| Repo | Role | Tech | Port |
|---|---|---|---|
| **palmgrade-vision** | **AI camera + inference (per line)** | **Python 3.11 / FastAPI** | **8001 / 8002 / 8003** |
| palmgrade-api | Business logic, auth, SSE broker | Node.js / Express | 2500 |
| palmgrade-frontend | Operator dashboard UI | Next.js 15 | 3050 |

Full system map: `../ARCHITECTURE.md`.

---

## Tech Stack

- Python 3.11, **FastAPI** + uvicorn
- **Ultralytics YOLO** (YOLOv8 + ByteTrack); torch/torchvision (CPU for dev, CUDA `cu126` for prod)
- OpenCV, NumPy
- **httpx** (cloud upload + realtime push), **APScheduler** (hourly batch upload), **SQLite**
  (`outbox.db` = antrean realtime ke API lokal; `UploadManifest` = state per-item batch R2), **boto3** (R2)
- **Hikrobot MVS SDK** (GigE industrial camera — prod only)
- **pymodbus** (Modbus-TCP client — PLC/ODOT integration, PC pabrik only, mati default)
- **Docker-only** (no host venv). Deps pinned in `requirements.txt` (torch installed separately in Dockerfile).

---

## Project Structure (key dirs)

```
src/palmgrade/
  main.py          # app factory + lifespan: camera init, workers, 10s watchdog, /captures mount, /ws/results
  core/            # config.py (Settings/env), dependencies.py (DI), logging.py, constants.py
  routes/          # endpoint declarations only → controllers
  controllers/     # request handlers
  services/        # business flow (capture, inspection, streaming, truck, health, result)
  repositories/    # file I/O (WebP/JSON) via LocalFileStorage
  pipelines/       # YOLO inference (realtime_inspection_pipeline, model_registry)
  workers/         # background threads + RuntimeState (capture / display / processing / event_broadcast / outbox_retry / batch_upload)
  integrations/    # camera/{hikrobot,opencv,photo}, notifications/(webhook), storage/, scheduler/, upload/ (R2Uploader + UploadManifest), outbox/ (OutboxStore)
  domain/          # pure rules + entities (no I/O)
  plc/             # PLC/ODOT Modbus-TCP integration, entirely self-contained — public surface is 3 functions (start_plc_worker/submit_grading/inputs)
  schemas/         # Pydantic request/response models
  license/         # optional Ed25519 license guard
docs/              # overview.md (DETAIL), architecture.md, backend-overview.md, SETUP.md
tests/unit/        # unit test murni-logic (pytest, no torch/cv2)
models/release/    # best_3class_v2.pt (required, NOT committed)
artifacts/line-N/  # runtime output per line (NOT committed)
```

Tooling: `pyproject.toml` (pytest + ruff config, TIDAK untuk build), `.github/workflows/ci.yml` (lint + test).

Layer rule (strict): `route → controller → service → repository / pipeline / integration`.
Per-layer do/don't: `docs/overview.md` + `docs/architecture.md`.

---

## Run / Build / Test

All via **`make`** (Docker only). From `palmgrade-vision/`:

| Cmd | What |
|---|---|
| `make up` | prod: copy MVS SDK + build GPU (`cu126`) + start 3 lines (TensorRT build **temp-disabled**, lihat bawah) |
| `make up-dev` | dev: build CPU (no SDK) + start 3 lines |
| `make restart` | **code-only change** — kode di-bind-mount (`.:/app`), jadi **tidak perlu rebuild** |
| `make start` / `make up-1\|2\|3` | start without rebuild (all / single line) |
| `make build-engine` | build TensorRT FP16 engine **once per GPU** (one-shot, auto-skip kalau sudah ada) |
| `make logs` / `make logs-1` | tail logs (combined / per line) |
| `make down` / `make ps` / `make rebuild` / `make rebuild-clean` / `make clean` | stop / status / rebuild / clean rebuild (`--no-cache`) / cleanup |

- **TensorRT (GPU speedup, akurasi sama) — SEMENTARA DINONAKTIFKAN**: install TensorRT di Dockerfile + step `build-engine` di `make up` di-comment (disk dev PC penuh saat unpack libnvinfer). Runtime **fallback ke `.pt`** otomatis (`pipelines/model_registry.py`). Di PC prod (disk lega): uncomment blok TensorRT di `Dockerfile` + baris `$(MAKE) build-engine` di `Makefile`, rebuild, lalu `make build-engine` — engine FP16 (`engines/<model>.sm<cc>.engine`, **hardware-locked**, tidak di-commit) dibangun sekali per GPU (~5–15 mnt). Detail: `docs/overview.md` § Docker/SDK/GPU.
- **`make up` cuma perlu** kalau dependency / `Dockerfile` / SDK berubah; untuk ubah kode pakai `make restart`.
- **Dev without a camera**: `.env` → `CAMERA_TYPE=opencv` + `CAMERA_VIDEO_PATH=/videos/<file>.mp4` (host `sawit/` is mounted at `/videos`).
- **Verify**: `curl :8001/health`; `curl :8001/health/detail` (camera_connected, gpu_available, workers, current_assignment_id); stream at `http://localhost:8001/api/video_feed`.
  ⚠️ `outbox_pending`/`outbox_failed` di `/health/detail` mengukur **jalur realtime ke API lokal**
  saja. Angka naik terus = API lokal tidak menjawab (cek `BACKEND_URL`). Angka itu **tidak**
  mengatakan apa-apa soal batch upload ke cloud — untuk itu baca log `Batch tick: N item eligible`
  dari `BatchUploadWorker` atau query `state/upload_manifest.db` langsung.
- **Tests / CI**: `tests/unit/` = unit test murni-logic (`rules`, `outbox_store`, `event_id` uuid5, streaming keep-alive, config validation, **license**: JWS Ed25519 verify + state machine + SQLite hash-chain) — jalan tanpa torch/cv2/SDK via **`pytest`** (config di `pyproject.toml`, `pythonpath=src`; async pakai `asyncio.run`, **bukan** pytest-asyncio). CI install deps ringan pure-python (`cryptography aiosqlite psutil httpx`) di samping `ruff pytest`. Lint via **`ruff check`** (scope: `tests/`, `domain/`, `integrations/outbox/`, `license/`, `plc/` — diperluas bertahap per modul yang sudah bersih). Semua jalan otomatis di **`.github/workflows/ci.yml`** tiap PR/push ke `staging`/`main` (runner ringan, tanpa GPU). `tests/integration` masih `.gitkeep` (butuh Docker + hardware). **Nambah test → utamakan logic murni; jangan seret framework berat/hardware ke CI.**
- From-zero prod setup (NVIDIA toolkit, MVS install, camera IP): `docs/SETUP.md`.

---

## HTTP Surface (this service)

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/health/detail` | detail = camera / gpu / workers / current_assignment_id (+ `outbox_pending`/`outbox_failed`, always `0` — outbox disabled) |
| GET | `/api/video_feed` | MJPEG live (multi-viewer) |
| GET | `/api/results_today` | today's results (read from disk) |
| POST | `/api/set_truck` | legacy set active truck |
| POST | `/api/capture_reject` | legacy manual reject capture |
| POST | `/internal/assignment` | ← from api: set current truck/assignment (`x-internal-secret`) |
| POST | `/internal/manual-reject` | ← from api: trigger manual reject (`x-internal-secret`) |
| WS | `/ws/results` | legacy result push |
| GET | `/captures/...` | static images (mount → `artifacts/`) |

---

## Integration Contracts (verified against palmgrade-api code)

**vision → api** — **dua jalur paralel, sengaja**:

| Jalur | Tujuan | Kapan | Gambar |
|---|---|---|---|
| `OutboxRetryWorker` (realtime) | `BACKEND_URL` = API **lokal** PC pabrik | poll 1 detik | path relatif → api meng-serve dari mount `artifacts/` |
| `BatchUploadWorker` (batch) | `UPLOAD_API_URL` = API **cloud** | tiap jam menit `UPLOAD_MINUTE` | di-`PUT` ke R2 dulu, event bawa URL R2 absolut |

`event_id` keduanya identik (uuid5 `machine_id:file_timestamp`), jadi kalaupun dua jalur ini
menunjuk API yang sama, POST kedua dibalas `already_processed` — bukan baris dobel.
⚠️ `BACKEND_URL` **wajib** API lokal. Menunjuknya ke `api.smagri.id` adalah yang membanjiri
produksi dengan ~1098 event tes pada 2026-08-09.

Kontrak jalur batch (gambar dulu ke R2, lalu teks ke API cloud):
- Image first: `PUT` to Cloudflare R2, then the text event references the public R2 URL.
- `POST {UPLOAD_API_URL}{BACKEND_API_VER}/internal/vision/events`
  → cloud `https://api.smagri.id/api/v1/internal/vision/events`
- Header **`x-webhook-secret: UPLOAD_API_SECRET`** (must equal the cloud API's `WEBHOOK_SECRET`)
- **Kill switch**: empty `R2_BUCKET` makes the whole batch a no-op (one `logger.warning` on the
  first tick, then quiet — easy to miss in a long-running log) — nothing reaches
  the cloud, and `/health/detail` will not tell you.
- Payload field contract (api validates via `VisionEventRequest` DTO):
  - `prediction` `"Acc"|"Rej"` (**required**)
  - `ripeness_status` `"ACC"|"REJ"` (**UPPERCASE**, `@IsIn`)
  - `tp_status` `"PASS"` or `null` (never `"TP"`)
  - `capture_type` `"auto"|"manual"`
  - `machine_id` UUID (must equal a `machines.id`)
  - `event_id` UUID (idempotency; **selalu** uuid5 deterministik, auto maupun manual), `timestamp` ISO **UTC-aware**, `truck_id` optional, `bounding_box` `{x_min,y_min,x_max,y_max}`
- api responds `200/201` or `{status:"already_processed"}` (both treated as delivered).

**api → vision** — header **`x-internal-secret: WEBHOOK_SECRET`**:
- `POST /internal/assignment` body `{machine_id, assignment_id, truck_id, assigned_at}`
- `POST /internal/manual-reject` body `{machine_id, assignment_id, requested_by, requested_at}`
- `GET /health` (line health check in api `getLines()`)

**Shared config:**
- `WEBHOOK_SECRET` — **one** secret, both directions; must equal `palmgrade-api` `WEBHOOK_SECRET`. **Fail-fast:** `Settings.validate_for_runtime()` raise saat `APP_ENV=production` & secret masih default (`supersecret123`) → container tolak start. **Wajib isi `WEBHOOK_SECRET` di `.env` PC prod** (dev tetap boleh default, cuma warning).
- `machine_id` — `LINE_1/2/3_MACHINE_ID` in `.env` = the three `machines.id` UUIDs in api Postgres.
  docker-compose falls back to seed UUIDs if unset.
- Saved images: api maps `machine_id → machines.line_code` and serves at
  `/api/v1/captures/<line_code>/...` (vision's `image_path` has no line segment).

**SSE events** api broadcasts to frontend after ingest: `inspection_saved`, `new_quality_control` (alias), `assignment_changed`.

Full endpoint / payload / env tables: `docs/backend-overview.md`.

---

## Critical Rules (full rationale → `docs/overview.md` § Invariants)

1. **Disk before API** — never POST events directly from a worker; **antrean yang bicara ke
   jaringan, bukan worker deteksi**. `FrameProcessingWorker` dan `capture_service` menulis WebP +
   JSON ke `artifacts/results/` lalu **satu baris** ke `outbox.db` (`build_event_payload()` dari
   `domain/vision_event.py`). Dua konsumen mengirimnya:
   - `OutboxRetryWorker` → API **lokal** (`BACKEND_URL`), poll 1 detik. Ini yang bikin operator
     lihat Grading History + gambar seketika, dan satu-satunya jalur yang hidup saat internet mati.
   - `BatchUploadWorker` → R2 + API **cloud** (`UPLOAD_API_URL`), tiap jam. Menemukan item lewat
     `_scan()` folder `results/` (**bukan** outbox), state per-item di `UploadManifest`.

   `event_id` = **uuid5 deterministik** (`machine_id:file_timestamp`) di **semua** jalur, jadi
   kirim ulang dibalas `already_processed`, bukan baris dobel. Jangan pernah pakai uuid4 di sini.

   `image_path` dari kedua worker deteksi **harus relatif** (`captures/results/<tgl>/<file>.webp`);
   api merakitnya jadi `{apiPrefix}/captures/{line_code}/...`. Hanya `BatchUploadWorker` yang
   menukarnya dengan URL R2 absolut, dan itu untuk cloud saja.

   Kelas kegagalan batch bersifat load-bearing: `_PoisonError` → poisoned + **continue** (satu item
   busuk tidak menyandera batch; file TIDAK dihapus); `_RequeueError` → requeue, lalu **break**
   kalau `batch_fatal=True` (jaringan/5xx/429/401/403 — kondisi global) tapi **continue** kalau
   `batch_fatal=False` (HTTP 404 = truck belum sinkron, kondisi per-item — break di situ bikin
   antrean `ORDER BY discovered_at ASC` kelaparan di belakangnya).
2. **`_processed_objects`** — never `discard()` an active track (single-trigger). Trim only IDs that are inactive (gone from `track_history`) **and** stale >300s.
3. **`state.lock`** around all physical camera access (`FrameCaptureWorker` + `capture_manual_reject`).
4. **MJPEG** — only `DisplayWorker` writes `state.latest_frame`, via `threading.Condition.notify_all()` (multi-viewer). It renders `last_yolo_frame` (paired with results) and runs at `STREAM_FPS` (default 12), decoupled from `CAMERA_FPS`.
5. **DI** (`core/dependencies.py`) — `@lru_cache` singletons **except** `get_capture_service()` / `get_health_service()` (camera injected at startup). `get_outbox_store()` may cache (SQLite singleton).
6. **Lifespan** (not `@app.on_event`); `repo_root = parents[3]`; every worker `run_loop` wraps `run_once` in `try/except`; `FrameCaptureWorker` needs `device_index` (so line-2/3 reconnect to the correct camera).
7. **`tp_status` = `"PASS"`** (not `"TP"`). **`image_url` = `captures/results/{date}/{ts}_auto.webp`** (consistent with `/captures` mount). Gambar disimpan **WebP** quality 65 (`JPEG_QUALITY_SAVE`); folder `errors/` **tidak ditulis lagi** — REJ ditemukan via metadata `ripeness_status`.
8. **`cv2.imwrite` failure → `LocalFileStorage.write_image` raises `IOError`** (no orphaned JSON records pointing at an image that was never written).
9. **Retention deletes source files** — `BatchUploadWorker._retention()` unlinks the WebP + JSON once an item is `done` and older than `UPLOAD_RETENTION_DAYS` (default 7). Local artifacts are therefore **not** a long-term archive; the cloud + R2 are.

---

## Conventions

- `snake_case` files/functions, `PascalCase` classes, `UPPER_SNAKE` constants (`core/constants.py`) & env vars.
- All paths via `Settings` (`core/config.py`) — never hardcode. New env var → add to `core/config.py` with a sane default.
- `CAMERA_TYPE`: `hikrobot` (prod) / `opencv` (dev: webcam or video file) / `photo` (test). Switching needs **no code edit**.
- ROI (`ROI_X1/Y1/X2/Y2`) coordinates are in **stream space** (`STREAM_WIDTH×STREAM_HEIGHT`, default 1280×720), not sensor space.

---

## Git Workflow

- Default branch `staging`; **PR-only** (main & staging protected). Flow: branch ← `staging` → PR → squash merge.
- Commit messages: **never** include "Co-Authored-By: Claude" or any AI reference.

---

## Pointers

- **`docs/overview.md`** — deep flows, ASCII diagrams, all invariants with rationale, worker/state model, Docker/SDK/GPU internals, prod deployment checklist, edge cases.
- `docs/architecture.md` — layer boundaries (final design; don't change without discussion).
- `docs/backend-overview.md` — full endpoint + event + env-var tables.
- `docs/plc-integration.md` — PLC/ODOT CN-8031 coil map, env vars, throughput ceiling, open hardware questions.
- `docs/SETUP.md` — from-zero prod setup (NVIDIA toolkit, MVS, camera IP, Docker build).
- `../ARCHITECTURE.md` — 3-repo system architecture.
