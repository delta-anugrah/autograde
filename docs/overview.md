# palmgrade-vision — Detailed Overview

> **The DETAIL doc** (read on-demand). The lean map is `../CLAUDE.md`.
> Even deeper, specialized docs: `architecture.md` (layer boundaries), `backend-overview.md`
> (full endpoint/env tables), `SETUP.md` (from-zero prod setup).

---

## 1. Layered Architecture — per-layer do/don't

`route → controller → service → repository / pipeline / integration`. Each layer has a strict boundary.

| Layer | Folder | May | Must NOT |
|---|---|---|---|
| Routes | `routes/` | path, method, `Depends()`, return type | any logic, file/model/queue access |
| Controllers | `controllers/` | take request, call **one** service, raise `HTTPException` | touch repository, queue, or YOLO |
| Services | `services/` | combine repo + pipeline + integration; run business flow | SQL, vendor SDK detail, direct file I/O |
| Repositories | `repositories/` | read/write JSON & JPEG via `LocalFileStorage` | PASS/FAIL rules, HTTP, inference, voting |
| Pipelines | `pipelines/` | YOLO inference, frame processing, draw boxes | HTTP, file save, business rules, queue |
| Domain | `domain/` | pure functions/dataclasses, zero I/O | import `cv2`/`httpx`/`fastapi`, read/write files |
| Workers | `workers/` | background loop, queue, lock, `RuntimeState` | return HTTP, save to file directly (delegate to repo) |

---

## 2. Worker & Runtime-State Model

`main.py` `lifespan()` starts (all daemon unless noted):

| Worker | Kind | Responsibility |
|---|---|---|
| `FrameCaptureWorker` | thread | grab frame from camera (under `state.lock`) → `state.latest_raw_frame` + `frame_queue`. Auto-reconnects with `device_index`. |
| `FrameProcessingWorker` | thread | YOLO inference from `frame_queue`; sets `state.last_yolo_frame` + `state.last_yolo_results` (paired); detection → save → outbox → `event_queue` |
| `DisplayWorker` | thread | the **only** writer of `state.latest_frame`: draw boxes → resize → draw ROI → JPEG encode → `frame_condition.notify_all()`. Runs at `STREAM_FPS` (default 12). |
| `OutboxRetryWorker` | thread | poll SQLite outbox every **1s**, POST pending events to api, mark delivered/failed |
| `EventBroadcastWorker` | asyncio task | drain `event_queue` → push to `/ws/results` WebSocket clients |
| `_watchdog` | asyncio task | every **10s**, restart any dead worker thread |

`UploadScheduler` (APScheduler) runs the daily artifact upload cron.

**Queues / sync primitives** (`workers/runtime_state.py`):
- `frame_queue` — raw frames, bounded (drop-old).
- `event_queue` — outgoing events for WebSocket, **drop-old** (`get_nowait()` + `put_nowait()`).
- `frame_condition` (`threading.Condition`) — MJPEG broadcast (multi-viewer; each viewer `wait(timeout=0.5)`).
- `state.lock` — guards physical camera access.
- `current_truck_id`, `current_assignment_id` — set by `POST /internal/assignment`.
- `last_successful_api_push`, `worker_threads`, `websocket_clients`, `main_loop`.

---

## 3. Detection Flow (single-trigger, not voting)

Model `best_3class_v2.pt` detects 3 classes in one pass: `acc`, `rej`, `tp`.

```
each YOLO frame (ByteTrack assigns track_id per object):
  label == "tp"                  → store in _last_tp (candidate, paired later)
  label in ("acc","rej") AND center inside ROI AND track not processed:
      area = (x2-x1)*(y2-y1)
      if area < MINIMUM_SIZE (460000) OR >1 fruit in ROI this frame → force "rej"
      _save_ripeness(): annotated WebP (quality 65) + {ts}_auto_ripeness.json
      if _last_tp: _save_tp(): {ts}_auto_tp.json (no image, same timestamp) then clear
      push event to event_queue (drop-old) for WebSocket
      if truck active (if truck_id:) → outbox.add_event(...)   # auto: gated on truck
          event_id = uuid5(machine_id:timestamp)  # deterministik → replay idempotent
      mark track processed LAST (_processed_objects.add + _processed_times)
      # processed di-set SETELAH outbox: crash mid-block → frame di-reprocess dgn
      # event_id sama → API balas already_processed → tidak double count
```

- `ResultRepository.list_today_results()` merges `_ripeness.json` + `_tp.json` per base_name.
- Manual reject (`CaptureService.capture_manual_reject`): full-frame capture marked `rej`,
  saved as `{ts}_manual_ripeness.json` (suffix `_ripeness` is required so it isn't read as legacy),
  **always** enqueued to outbox (truck may be `null`). `bounding_box` = full frame `{0,0,width,height}`.

**ROI box:** `ROI_X1/Y1/X2/Y2` in **stream space** (`STREAM_WIDTH×STREAM_HEIGHT`, default 1280×720),
NOT sensor space — operators calibrate from what they see in the browser. Center `(cx,cy)` must be
inside the box. `0,0,0,0` = full frame (X2=0→stream width, Y2=0→stream height); require `X2>X1` & `Y2>Y1`.
TP is exempt from the ROI check. `draw_roi()` runs in `DisplayWorker` **after** resize.

**DisplayWorker draw order:** `draw_boxes()` (on `last_yolo_frame`) → `cv2.resize()` → `draw_roi()`.
Render boxes over `last_yolo_frame` (paired with results), **never** over `latest_raw_frame` — on CPU,
inference can take 0.5–2s and the conveyor moves, so boxes would land in the wrong place. Fallback to
`latest_raw_frame` only before the first YOLO run.

---

## 4. Outbox Delivery (durable, at-least-once)

```
FrameProcessingWorker / CaptureService
  → OutboxStore.add_event(event_id, machine_id, payload)        # write to SQLite first
      → OutboxRetryWorker (thread, poll 1s)
          → POST {canonical_events_url}  header x-webhook-secret: WEBHOOK_SECRET
              → palmgrade-api  /api/v1/internal/vision/events
```

- `canonical_events_url` = `{backend_url}{backend_api_ver}/internal/vision/events` (`Settings`).
- Backoff: base **5s**, exponential to cap **600s**, max **50** retries (`outbox_store.py`).
- Delivered if api returns `200/201` **or** body contains `already_processed`.
- Survives restart — `artifacts/outbox.db` per container. If api down/offline, events are **not** lost.
- SQLite durability eksplisit: **`PRAGMA journal_mode=WAL` + `synchronous=FULL`** — commit di-fsync, event yang sudah tercatat selamat dari mati listrik (write rate rendah, biaya fsync ringan).
- `event_id`: **auto** = uuid5 deterministik dari `machine_id:timestamp` (re-process pasca-crash → id sama → idempotent); **manual reject** = uuid4.
- `add_event()` is wrapped in `try/except` + `logger.error` (never `try/except: pass`) so a full disk
  logs an error instead of crashing the detection loop.

**Event payload (field names exact):**
```json
{
  "event_id": "uuid (auto: uuid5 deterministik, manual: uuid4)",
  "machine_id": "uuid",
  "assignment_id": "uuid-or-null",
  "truck_id": "uuid-or-null",
  "timestamp": "ISO-8601 UTC-aware (+00:00)",
  "image_path": "captures/results/{date}/{ts}_auto.webp",
  "prediction": "Acc | Rej",
  "ripeness_status": "ACC | REJ",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS | null",
  "tp_confidence": 0.88,
  "capture_type": "auto | manual",
  "bounding_box": { "x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100 }
}
```
Contracts: `ripeness_status` UPPERCASE; `prediction` required; `tp_status` `"PASS"` or `null`
(never `"TP"`); `event_id` is the api idempotency key; `assignment_id` from `state.current_assignment_id`.

---

## 5. Integration Contract (cross-checked vs palmgrade-api code)

**vision → api**
- `POST {BACKEND_URL}{BACKEND_API_VER}/internal/vision/events`, header `x-webhook-secret`
  (`webhook.middleware.ts` checks equality with `process.env.WEBHOOK_SECRET`).
- api validates `VisionEventRequest` DTO (`@IsIn` on prediction/ripeness/tp/capture_type, `@IsUUID`
  on machine_id). `truck_id`/`bounding_box` optional on the api side.

**api → vision** (`gradingConsole.service.impl.ts`), header `x-internal-secret`:
- `POST {vision_base_url}/internal/assignment` `{machine_id, assignment_id, truck_id, assigned_at}`
  → `AssignmentSyncRequest` → sets `state.current_truck_id` + `state.current_assignment_id`.
- `POST {vision_base_url}/internal/manual-reject` `{machine_id, assignment_id, requested_by, requested_at}`
  → `ManualRejectCommandRequest` → `capture_manual_reject()` via executor.
- `GET {vision_base_url}/health` for the line health check.

**Shared:** one `WEBHOOK_SECRET` both directions; `LINE_1/2/3_MACHINE_ID` = the three `machines.id`
UUIDs (docker-compose falls back to seed UUIDs if unset). api maps `machine_id → machines.line_code`
to serve images at `/api/v1/captures/<line_code>/...`. api SSE events after ingest:
`inspection_saved`, `new_quality_control`, `assignment_changed`.

> Day-boundary note: **event** `timestamp` sekarang UTC-aware (`datetime.now(timezone.utc)`) — api
> parse dengan benar tanpa asumsi TZ. File JSON di disk masih pakai naive local time (nama folder
> tanggal + `results_today` mengikuti jam lokal container).

---

## 6. Invariants — full rationale (don't change without discussion)

0. **Outbox before API.** Never POST events directly from a worker. `CaptureService` always
   `add_event()`; `FrameProcessingWorker` only inside `if truck_id:` — auto detection without an
   active truck is intentionally not sent (still saved to disk + WebSocket), because the api needs a
   truck/assignment to attribute the event.
1. **`_processed_objects`.** After saving a track_id, add it so the next iteration `continue`s
   (single-trigger). Never `discard()` an active track. `run_once` trims only IDs that are gone from
   `track_history` **and** stale >300s (`_processed_times`) — pure memory control, can't re-trigger
   (the fruit left the frame long ago).
   **Ordering:** `processed` di-set **SETELAH** save + outbox write (bukan sebelum). Kalau crash di
   tengah blok, track belum processed → frame berikutnya reprocess → `event_id` uuid5 deterministik
   (`machine_id:timestamp`) menghasilkan id sama → API idempotent, tidak double count. Track tanpa
   truck aktif tetap ditandai processed supaya tidak re-trigger.
2. **`state.lock`** around all physical camera access (`FrameCaptureWorker.run_once` +
   `capture_manual_reject`) — concurrent Hikrobot SDK access can crash.
3. **MJPEG via `threading.Condition`**, not `result_queue` — the old queue pattern served only one
   viewer. `event_queue` stays drop-old.
4. **DI** (`core/dependencies.py`): `@lru_cache` singletons; `get_outbox_store()` may cache (SQLite +
   `threading.Lock`, fresh connection per op). **NOT** cached: `get_capture_service()` /
   `get_health_service()` — they call `get_camera()` which raises before startup; caching would freeze
   `_camera = None`.
5. **`repo_root = parents[3]`** — `src/palmgrade/core/config.py` → 3 levels up = `/app` in Docker.
6. **`lifespan`** (not deprecated `@app.on_event`); scheduler + camera disconnect are lifespan locals.
7. **MJPEG written only by `DisplayWorker`** — two writers to `state.latest_frame` cause flicker.
   It renders `last_yolo_frame` (paired with `last_yolo_results`), runs at `STREAM_FPS` (default 12),
   decoupled from `CAMERA_FPS` (code default 30; docker-compose sets 25).
8. **Manual capture JSON** uses suffix `_ripeness` so `list_today_results()` reads it correctly.
9. **Every worker `run_loop` wraps `run_once` in `try/except`** + `logger.exception` — without it the
   thread dies silently and the watchdog restarts without a stack trace.
10. **`FrameCaptureWorker` needs `device_index`** — reconnect calls `camera.connect(index=...)`; a bare
    `connect()` (default 0) makes line-2/3 reconnect to the wrong camera.
11. **`cv2.imwrite` failure raises `IOError`** in `LocalFileStorage.write_image` — a silent warning
    would leave orphaned JSON + outbox events pointing at a missing image. Auto path: caught by
    `run_loop` (skip 1 frame). Manual path: propagates → 500 to operator.

---

## 7. Camera Abstraction

`CAMERA_TYPE` (default `hikrobot`) selects the implementation in `lifespan()` — no code edit to switch:

| `CAMERA_TYPE` | Class | When |
|---|---|---|
| `hikrobot` | `HikrobotCamera` | production (needs MVS SDK + GigE hardware) |
| `opencv` | `OpenCVCamera` | dev — webcam (`CAMERA_DEVICE_INDEX`) or video file (`CAMERA_VIDEO_PATH`) |
| `photo` | `PhotoCamera` | testing — single image looped (`CAMERA_PHOTO_PATH`) |

`CameraSource` ABC: `connect(index)`, `grab_frame() -> np.ndarray | None`, `disconnect()`.

**Graceful startup:** `main.py` wraps `camera.connect()` in try/except for hikrobot. If absent, the app
still runs (`health.detail.camera_connected=false`), `FrameCaptureWorker` retries ~every 30s, and
`grab_frame()` returns `None` (no crash). Plug the camera in (MVS closed) → `connected=true`, no restart.

---

## 8. Docker / SDK / GPU Internals

**Docker-only** (no host venv). Volumes: `.:/app` (hot-reload), anonymous `/app/.venv` (shadow host),
`./artifacts/line-N:/app/artifacts`, `./models:/app/models:ro`. `entrypoint.sh` lives at `/entrypoint.sh`
(outside `/app`, so the `.:/app` mount can't shadow it). `load_dotenv(override=False)` in `main.py`;
docker-compose `environment:` always wins over host `.env`.

**Shared image:** only `ripe-line-1` has `build:` + `image: palmgrade-vision:latest`; line-2/3 reuse the
image (build once, ~20GB saved). Don't re-add `build:` to line-2/3.

**`network_mode: host`** — required for GigE Vision: `MV_CC_EnumDevices()` uses UDP broadcast that the
Docker bridge blocks. Consequence: `ports:`/`extra_hosts:` are ignored — each container binds its own
`APP_PORT` (8001/8002/8003).

**GPU passthrough** (`deploy.resources.reservations.devices: nvidia/all/[gpu]`) — needs NVIDIA Container
Toolkit on host (add the NVIDIA apt repo first; `apt install nvidia-container-toolkit` alone isn't enough
— see `SETUP.md`). Without it YOLO runs on CPU (~10× slower).

**TensorRT engine (SEMENTARA DINONAKTIFKAN):** normalnya `make build-engine` (one-shot container,
`scripts/build_engine.py`) export `.pt` → engine FP16 di `engines/<model>.sm<cc>.engine` — **hardware-locked**
per compute capability (`Settings.engine_path_for_gpu`), tidak di-commit, auto-skip kalau sudah ada;
runtime (`pipelines/model_registry.py`) auto-pakai engine dan **fallback ke `.pt`** kalau tidak ada.
Saat ini install TensorRT di `Dockerfile` dan step `$(MAKE) build-engine` di target `up` **di-comment**
(unpack libnvinfer gagal "no space left on device" di disk dev yang ketat). Runtime jalan via `.pt`.
Re-enable di PC prod: uncomment kedua blok → rebuild → `make build-engine` (~5–15 mnt pertama kali).
PENTING: TensorRT wajib di-install dari index NVIDIA (`https://pypi.nvidia.com`, wheel binary) —
PyPI publik cuma punya source stub yang bikin pip hang di "Preparing metadata".

**SDK flow in `make up`:** `mkdir -p sdk/lib64` → `cp -r /opt/MVS/lib/64/. sdk/lib64/` +
`cp -r /opt/MVS/Samples/64/Python/MvImport sdk/MvImport` → Dockerfile `COPY sdk/ /tmp/sdk/` → copy into
`/opt/MVS/lib/64` + site-packages → `ENV MVCAM_COMMON_RUNENV=/opt/MVS/lib`. The **whole** `lib64` is
needed (not just `libMvCameraControl.so`): `MV_CC_EnumDevices()` dynamically loads the transport layer
(`MvProducerGEV.cti`, `libMVGigEVisionSDK.so`); missing them → `MV_E_LOAD_LIBRARY (0x8000000C)`.

**Production deployment checklist (new PC — order matters):**
1. Install NVIDIA Container Toolkit → verify `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi`.
2. Install Hikrobot MVS SDK at `/opt/MVS/` (`SETUP.md § 3`).
3. `mkdir -p models/release` + copy `best_3class_v2.pt`.
4. `.env`: `LINE_1/2/3_MACHINE_ID` (real UUIDs), `BACKEND_URL`, `WEBHOOK_SECRET`, `CAMERA_TYPE=hikrobot`, `CAMERA_FPS=10` (samakan dengan Acquisition Frame Rate kamera — `SETUP.md § 6.3`, alasan bandwidth 3 kamera).
5. `make up`.
6. Verify `curl :8001/health/detail | grep -E "gpu_available|camera_connected"`.

**`requirements.txt`:** never replace with `pip freeze` from elsewhere. Only what the source imports:
`fastapi`, `uvicorn[standard]`, `python-multipart`, `python-dotenv`, `ultralytics`, `numpy`,
`opencv-python`, `httpx`, `pydantic`, `apscheduler`, `aiosqlite`, `cryptography`, `psutil`
(torch/torchvision are installed separately in the Dockerfile per `TORCH_VARIANT`).

---

## 9. Artifact Layout

```
artifacts/line-N/   (host) ↔ /app/artifacts (container)
  results/{YYYY-MM-DD}/{ts}_auto.webp + {ts}_auto_ripeness.json [+ {ts}_auto_tp.json]
                       {ts}_manual.webp + {ts}_manual_ripeness.json   # manual reject
  captures/                 # legacy — dibuat saat startup, TIDAK ditulis lagi
  errors/                   # legacy — dibuat saat startup, TIDAK ditulis lagi (REJ via metadata)
  logs/
  outbox.db                 # SQLite durable outbox (WAL + synchronous=FULL)
```
Gambar disimpan **WebP quality 65** (`JPEG_QUALITY_SAVE` di `core/constants.py` — nama konstanta
legacy, berlaku untuk WebP juga; `LocalFileStorage.write_image` pilih codec dari ekstensi file).
Served by FastAPI `StaticFiles` mount `/captures` → `artifacts/`, so `image_url`
`captures/results/{date}/{file}` resolves on the vision side. (The api re-serves per line under
`/api/v1/captures/<line_code>/...`.)

---

## 10. License Guard (optional, default off)

`LIC_ENABLED=true` adds `LicenseGuardMiddleware` (Ed25519 JWS verify, device fingerprint,
aiosqlite cache + hash-chain audit, `SyncClient` to license server). Added before CORS so a 403 still
gets CORS headers. `LicenseManager` / `LicenseLocalRepo` / `SyncClient` live in `license/`.
