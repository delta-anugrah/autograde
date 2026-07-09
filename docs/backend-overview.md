# Backend Overview — palmgrade-vision

Rangkuman teknis `palmgrade-vision` — Python AI camera service untuk sistem grading kelapa sawit.

## Tujuan Project

Menerima feed kamera industri Hikrobot, menjalankan model YOLO secara realtime,
mengklasifikasi kematangan buah sawit (3 kelas), menyimpan hasil inspeksi ke file,
dan mengirimkan event ke `palmgrade-api` via OutboxStore (SQLite durable delivery).

Dijalankan sebagai **3 container terpisah** (line 1/2/3), masing-masing satu port dan satu kamera.

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| Framework | FastAPI |
| Server | Uvicorn |
| Model inference | Ultralytics YOLO (YOLOv8) |
| Computer vision | OpenCV |
| Deep learning | PyTorch |
| Camera SDK | MvImport (Hikrobot proprietary) |
| HTTP client | httpx (async) |
| Scheduler | APScheduler |
| Config | python-dotenv + dataclass |
| Schema validation | Pydantic |

---

## Folder Structure

```
palmgrade-vision/
  src/
    palmgrade/
      main.py                  # FastAPI app factory + middleware + lifecycle

      routes/                  # Hanya deklarasi endpoint dan router wiring
      controllers/             # Terima request, panggil service, return response
      services/                # Orchestration dan business flow
      repositories/            # Baca/tulis file (JSON, WebP)
      pipelines/               # Logic YOLO inference + frame processing
      integrations/
        camera/                # HikrobotCamera / OpenCVCamera / PhotoCamera
        notifications/         # WebhookClient (httpx async) — legacy, not used for main flow
        outbox/                # OutboxStore — SQLite durable event persistence
        storage/               # LocalFileStorage (read/write JSON + WebP)
        scheduler/             # APScheduler daily upload cron
      workers/                 # Background threads + asyncio tasks
      domain/                  # Business rule murni — tidak ada I/O
      schemas/                 # Pydantic request/response schemas
      core/                    # Config, logging, constants, DI wiring
      license/                 # License guard (Ed25519 JWS, optional)

  cli/                         # Script CLI offline (training, predict)
  models/
    release/                   # Model .pt produksi — tidak di-commit ke git
  artifacts/                   # Output runtime — tidak di-commit ke git
  docs/
  Dockerfile
  docker-compose.yml           # 3 services: line-1 (8001), line-2 (8002), line-3 (8003)
  requirements.txt
  .env / .env.example
```

---

## Layer Responsibilities

| Layer | Boleh | Tidak Boleh |
|---|---|---|
| `routes/` | Deklarasi endpoint, include controller | Logic apapun |
| `controllers/` | Terima request, return response, HTTPException | Query DB, akses model langsung |
| `services/` | Orchestrasi, gabungkan repo + pipeline | Raw SQL, detail SDK, return HTTP |
| `repositories/` | Baca/tulis file JSON dan WebP | Business rule, HTTP call, inference |
| `pipelines/` | YOLO inference, frame processing, draw boxes | HTTP, persistence, business rule |
| `integrations/` | Akses sistem eksternal (kamera, webhook, storage) | Business rule |
| `workers/` | Background loop, queue, hold lock, RuntimeState | Langsung return HTTP response |
| `domain/` | Pure function, pure dataclass — zero I/O | Import cv2, fastapi, httpx; baca/tulis file |

---

## Detection Model

1 model (`best_3class_v2.pt`) mendeteksi 3 kelas sekaligus:
- `acc` — buah matang / diterima
- `rej` — buah tidak matang / ditolak
- `tp` — tangkai panjang (long stalk)

**Single-trigger detection** (bukan vote):
- Track setiap buah via ByteTrack `track_id`
- Saat pusat bounding box buah berada di dalam ROI box → simpan langsung (satu kali per track_id)
- `MINIMUM_SIZE = 460000 px²` — buah < threshold → auto `rej`
- TP yang terdeteksi disimpan sebagai JSON terpisah, dipasangkan dengan buah via timestamp
- TP tidak dicek ROI — selalu diterima dari posisi manapun

**ROI Box Detection Zone:**
- Dikontrol via env var: `ROI_X1`, `ROI_Y1`, `ROI_X2`, `ROI_Y2` (semua dalam pixel)
- Default `0,0,0,0` = full frame (semua objek eligible)
- `ROI_X2=0` → otomatis jadi lebar frame; `ROI_Y2=0` → otomatis jadi tinggi frame
- Ditampilkan sebagai overlay kuning semi-transparan (25% opacity) di MJPEG stream

---

## API Endpoints

### `GET /api/video_feed`

MJPEG live stream dari kamera.

- **Response:** `StreamingResponse`, `Content-Type: multipart/x-mixed-replace; boundary=frame`
- **Dikonsumsi FE:** `<img src="${LINE_N_URL}/api/video_feed" />`

---

### `GET /api/results_today`

Semua hasil grading hari ini.

- **Response:**
  ```json
  [
    {
      "id": "2026-05-18_103000_123456",
      "ripeness_status": "acc",
      "ripeness_confidence": 0.92,
      "tp_status": "PASS",
      "tp_confidence": 0.88,
      "timestamp": "2026-05-18T10:30:00.123456",
      "image_url": "captures/results/2026-05-18/2026-05-18_103000_auto.webp",
      "capture_type": "auto",
      "truck_id": "uuid-or-null",
      "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
    }
  ]
  ```
- Data dibaca dari `_ripeness.json` dan `_tp.json` di `artifacts/results/{YYYY-MM-DD}/`.

---

### `POST /api/set_truck` (legacy)

Set truck ID aktif untuk line ini secara langsung ke vision.

- **Request body:** `{ "truck_id": "uuid" }`
- **Response:** `{ "message": "Truck ID set", "truck_id": "uuid" }`
- **Side effect:** Menyimpan ke `RuntimeState.current_truck_id`. Masih aktif tapi operator sebaiknya pakai API `/api/v1/grading-console/lines/:id/assign-truck` — API akan push ke `/internal/assignment` yang juga set `current_assignment_id`.

### `POST /internal/assignment`

Terima assignment dari palmgrade-api. Protected by `x-internal-secret: WEBHOOK_SECRET`.

- **Request body:** `{ "machine_id", "assignment_id", "truck_id", "assigned_at" }`
- **Response:** `{ "accepted": true, "machine_id", "truck_id", "assignment_id" }`
- **Side effect:** Set `state.current_truck_id` + `state.current_assignment_id` — semua event selanjutnya punya `assignment_id` ini.

### `POST /internal/manual-reject`

Terima command manual reject dari palmgrade-api. Protected by `x-internal-secret: WEBHOOK_SECRET`.

- **Request body:** `{ "machine_id", "assignment_id", "requested_by", "requested_at" }`
- **Response:** `{ "accepted": true, "message": "capture_reject_requested" }`
- **Side effect:** Trigger `capture_manual_reject()` via `run_in_executor` — event ditulis ke OutboxStore.

---

### `POST /api/capture_reject`

Capture frame saat ini secara manual, langsung mark sebagai `rej`.

- **Request body:** tidak ada
- **Response:**
  ```json
  {
    "message": "Manual capture saved",
    "ripeness_status": "rej",
    "ripeness_confidence": 1.0,
    "tp_status": null,
    "tp_confidence": null,
    "timestamp": "...",
    "image_url": "captures/results/2026-05-18/..._manual.webp",
    "capture_type": "manual",
    "truck_id": "uuid-or-null"
  }
  ```
- **Side effect:** Simpan WebP + metadata JSON ke `results/{date}/`, tulis ke OutboxStore, push ke `event_queue` untuk WebSocket broadcast.

---

### `GET /health/detail`

Status operasional container.

- **Response:**
  ```json
  {
    "status": "ok",
    "environment": "production",
    "camera_type": "hikrobot",
    "camera_connected": true,
    "gpu_available": true,
    "gpu_device": "NVIDIA GeForce GTX 1650",
    "machine_id": "uuid-from-machines-table",
    "workers": [
      { "name": "capture", "alive": true },
      { "name": "display", "alive": true },
      { "name": "processing", "alive": true },
      { "name": "outbox_retry", "alive": true }
    ],
    "outbox_pending": 0,
    "current_assignment_id": "uuid-or-null",
    "last_successful_api_push": "ISO-timestamp-or-null"
  }
  ```

---

> Info model dan device yang aktif tersedia di `GET /health/detail` (`gpu_available`, `gpu_device`, `camera_type`, dst.) — tidak ada endpoint `/api/inspection/status` terpisah.

---

### `WebSocket /ws/results`

Push event realtime ke client saat ada detection baru. Legacy endpoint — masih aktif tapi FE utama memakai SSE dari `palmgrade-api`.

---

## Realtime Processing Flow

```
Hikrobot Camera (GigE via RJ45 LAN)
  ↓ [FrameCaptureWorker — daemon thread, holds state.lock]
  │    Grab timeout: 100ms. Setelah 5 failures → _try_reconnect() (backoff 1-30s)
  │    Reconnect pakai self._device_index (0/1/2 per line)
  ↓
frame_queue                      state.latest_raw_frame
  ↓                                       ↓
  ↓ [FrameProcessingWorker]    [DisplayWorker — sole MJPEG writer]
  ├── YOLO track() → detect     ├── draw_boxes() + zone lines
  ├── direction-aware zone       ├── resize to STREAM_WIDTH×STREAM_HEIGHT
  ├── _processed_objects check   └── imencode → state.latest_frame
  ├── Single-trigger save:            + frame_condition.notify_all()
  │     ├── write_image() WebP
  │     ├── write_json() _ripeness.json
  │     ├── write_json() _tp.json (if TP)
  │     ├── event_queue.put_nowait()
  │     └── OutboxStore.add_event()  ← SQLite durable (auto: hanya jika ada truck aktif)
  └── state.last_yolo_results (read by DisplayWorker)
  ↓ [EventBroadcastWorker — asyncio task]
WebSocket clients

state.latest_frame
  ↓ [generate_frames() — satu per viewer, wait frame_condition]
MJPEG stream → semua browser secara bersamaan

[_watchdog — asyncio coroutine, every 10s]
  └── checks thread.is_alive() → restart jika mati
      (worker object dipertahankan, _processed_objects survive restart)
```

**MJPEG broadcast:** `threading.Condition` (`frame_condition.notify_all()`) — semua viewer dapat frame yang sama.
`DisplayWorker` adalah **satu-satunya writer** ke `state.latest_frame`. Frame di-resize ke `STREAM_WIDTH×STREAM_HEIGHT` sebelum encode — default 1280×720.

**Drop-old policy pada `event_queue`:** `get_nowait()` + `put_nowait()` — jangan `put()` blocking.

**Lock policy:** `FrameCaptureWorker` dan `CaptureService` keduanya akses kamera fisik.
Keduanya **wajib** acquire `state.lock` sebelum memanggil `camera.grab_frame()`.

**Worker resilience:**
- Semua `run_loop()` dibungkus `try/except` — crash di-log, thread tidak mati
- `_watchdog` coroutine restart thread yang mati setiap 10s
- Camera reconnect otomatis setelah 5 consecutive grab failures

---

## File & Path Conventions

```
artifacts/
  results/
    {YYYY-MM-DD}/
      {timestamp}_auto.webp             # Annotated frame buah (WebP, quality 65)
      {timestamp}_auto_ripeness.json    # Metadata grading
      {timestamp}_auto_tp.json          # Metadata TP (jika ada)
      {timestamp}_manual.webp           # Manual capture
      {timestamp}_manual_ripeness.json  # suffix _ripeness wajib — dibaca oleh list_today_results()
  captures/                             # legacy — tidak ditulis lagi
  errors/                               # legacy — tidak ditulis lagi (REJ ditemukan via metadata ripeness_status)
  logs/
  outbox.db                             # SQLite durable outbox (WAL + synchronous=FULL)
```

`image_url` di response: `captures/results/{date}/{timestamp}_auto.webp`

FastAPI mount static: `app.mount("/captures", StaticFiles(directory="artifacts"))`

FE akses via: `${LINE_N_URL}/captures/results/{date}/{filename}`

---

## Event Delivery ke palmgrade-api (via OutboxStore)

Setiap detection final (auto atau manual) ditulis ke OutboxStore dulu, lalu `OutboxRetryWorker` deliver ke API.

```
FrameProcessingWorker / CaptureService
    → OutboxStore.add_event(event_id, machine_id, payload)  [SQLite write]
        → OutboxRetryWorker (daemon thread, poll 1s)
            → POST {canonical_events_url}
               = {BACKEND_URL}{BACKEND_API_VER}/internal/vision/events
```

**Headers:** `x-webhook-secret: {WEBHOOK_SECRET}`, `Content-Type: application/json`

**Payload** — field names dan values HARUS tepat:
```json
{
  "event_id": "uuid",
  "assignment_id": "uuid-or-null",
  "machine_id": "uuid-dari-tabel-machines",
  "truck_id": "uuid",
  "timestamp": "2026-05-18T10:30:00.123456+00:00",
  "image_path": "captures/results/2026-05-18/2026-05-18_103000_auto.webp",
  "prediction": "Acc",
  "ripeness_status": "ACC",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS",
  "tp_confidence": 0.88,
  "capture_type": "auto",
  "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
}
```

**Kontrak penting:**
- `event_id`: dipakai API untuk idempotency (sparse unique index). **Auto** = uuid5 deterministik dari `machine_id:timestamp` (reprocess pasca-crash → id sama → tidak double count); **manual** = uuid4
- `timestamp`: ISO-8601 **UTC-aware** (`datetime.now(timezone.utc)`)
- `assignment_id`: dari `state.current_assignment_id` — set saat `/internal/assignment` dipanggil
- `prediction`: `"Acc"` / `"Rej"` — required
- `ripeness_status`: `"ACC"` / `"REJ"` UPPERCASE
- `tp_status`: `"PASS"` / `null` — BUKAN `"TP"`
- `truck_id`: **auto detection** (`FrameProcessingWorker`) di-skip dari outbox kalau `None` (belum set truck) — hasil tetap disimpan ke disk + WebSocket. **Manual reject** (`CaptureService`) selalu ditulis ke outbox walau `truck_id=None`.
- API returns `{status: "already_processed"}` jika `event_id` duplikat — OutboxRetryWorker delete event

**OutboxStore (`artifacts/outbox.db`):**
- SQLite file per container — survive restart container
- Exponential backoff: 5s base, 600s cap, max 50 retries
- `pending_count()` ditampilkan di `/health/detail`

---

## Environment Variables

| Variable | Default | Keterangan |
|---|---|---|
| `APP_PORT` | `8000` | Port server |
| `APP_HOST` | `0.0.0.0` | Host server |
| `FRONTEND_URL` | `*` | CORS allowed origin |
| `ENABLE_WEBHOOK` | `true` | Toggle webhook |
| `BACKEND_URL` | `http://localhost:2500` | palmgrade-api base URL |
| `BACKEND_API_VER` | `/api/v1` | Prefix versi API untuk canonical events URL |
| `WEBHOOK_SECRET` | — | Shared secret header, harus cocok dengan palmgrade-api |
| `MODEL_FILE` | `best_3class_v2.pt` | Nama file model di `models/release/` |
| `CONF_THRESHOLD` | `0.75` | Minimum confidence YOLO |
| `MINIMUM_SIZE` | `460000` | Minimum area bounding box (px²) — di bawah ini auto rej |
| `CAMERA_TYPE` | `hikrobot` | Sumber kamera: `hikrobot` / `opencv` (webcam atau video file) / `photo` |
| `CAMERA_DEVICE_INDEX` | `0` | Index device webcam (dipakai kalau `CAMERA_TYPE=opencv` tanpa `CAMERA_VIDEO_PATH`) |
| `CAMERA_VIDEO_PATH` | — | Path video file di dalam container (dipakai kalau `CAMERA_TYPE=opencv`) |
| `MACHINE_ID` | — | UUID dari tabel `machines` di PostgreSQL — berbeda per container |
| `ROI_X1` | `0` | Batas kiri area deteksi (px) |
| `ROI_Y1` | `0` | Batas atas area deteksi (px) |
| `ROI_X2` | `0` | Batas kanan area deteksi (px) — `0` = lebar penuh frame |
| `ROI_Y2` | `0` | Batas bawah area deteksi (px) — `0` = tinggi penuh frame |
| `STREAM_WIDTH` | `1280` | Lebar frame MJPEG stream (setelah resize, sebelum encode) |
| `STREAM_HEIGHT` | `720` | Tinggi frame MJPEG stream |
| `STREAM_FPS` | `12` | FPS MJPEG stream — decoupled dari `CAMERA_FPS` |
| `YOLO_SKIP_FRAMES` | `1` | Jalankan YOLO tiap N frame (`1` = produksi; `>1` hemat CPU saat tes video) |
| `UPLOAD_HOUR` | `0` | Jam upload otomatis (cron) |
| `UPLOAD_MINUTE` | `0` | Menit upload otomatis (cron) |
| `DESTINATION_UPLOAD` | — | Path tujuan upload hasil harian |
| `LIC_ENABLED` | `false` | Aktifkan license guard |
| `LIC_SERVER_URL` | — | URL license server |
| `LIC_API_KEY` | — | API key license server |
| `LIC_PUBKEY_PEM` | — | Public key Ed25519 untuk verifikasi JWS |

---

## Models

| File | Keterangan |
|---|---|
| `models/release/best_3class_v2.pt` | Model utama — deteksi 3 kelas: acc, rej, tp. v2: dataset 2x lebih besar, TP conf lebih stabil |

Model di-load saat startup. Jika file tidak ditemukan, server gagal start.
Model tidak di-commit ke git (ada di `.gitignore` via `*.pt`).
