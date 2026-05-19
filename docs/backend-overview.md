# Backend Overview — palmgrade-vision

Rangkuman teknis `palmgrade-vision` — Python AI camera service untuk sistem grading kelapa sawit.

## Tujuan Project

Menerima feed kamera industri Hikrobot, menjalankan model YOLO secara realtime,
mengklasifikasi kematangan buah sawit (3 kelas), menyimpan hasil inspeksi ke file,
dan mengirimkan webhook ke `palmgrade-api`.

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
      repositories/            # Baca/tulis file (JSON, JPEG)
      pipelines/               # Logic YOLO inference + frame processing
      integrations/
        camera/                # HikrobotCamera / OpenCVCamera / PhotoCamera
        notifications/         # WebhookClient (httpx async)
        storage/               # LocalFileStorage (read/write JSON + JPEG)
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
| `repositories/` | Baca/tulis file JSON dan JPEG | Business rule, HTTP call, inference |
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
- Saat buah melewati zona deteksi → simpan langsung (satu kali per track_id)
- `MINIMUM_SIZE = 460000 px²` — buah < threshold → auto `rej`
- TP yang terdeteksi disimpan sebagai JSON terpisah, dipasangkan dengan buah via timestamp

---

## API Endpoints

### `GET /api/video_feed`

MJPEG live stream dari kamera.

- **Response:** `StreamingResponse`, `Content-Type: multipart/x-mixed-replace; boundary=frame`
- **Dikonsumsi FE:** `<img src="${LINE_N_URL}/api/video_feed" />`

---

### `GET /api/results/today`

Semua hasil grading hari ini.

- **Response:**
  ```json
  [
    {
      "id": "2026-05-18_103000_123456",
      "ripeness_status": "acc",
      "ripeness_confidence": 0.92,
      "tp_status": "TP",
      "tp_confidence": 0.88,
      "timestamp": "2026-05-18T10:30:00.123456",
      "image_url": "captures/results/2026-05-18/2026-05-18_103000_auto.jpg",
      "capture_type": "auto",
      "truck_id": "uuid-or-null",
      "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
    }
  ]
  ```
- Data dibaca dari `_ripeness.json` dan `_tp.json` di `artifacts/results/{YYYY-MM-DD}/`.

---

### `POST /api/set_truck`

Set truck ID aktif untuk line ini.

- **Request body:** `{ "truck_id": "uuid" }`
- **Response:** `{ "message": "Truck ID set", "truck_id": "uuid" }`
- **Side effect:** Menyimpan ke `RuntimeState.current_truck_id`. Semua auto detection setelah ini di-tag dengan truck_id ini.

---

### `POST /api/manual_capture`

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
    "image_url": "captures/results/2026-05-18/..._manual.jpg",
    "capture_type": "manual",
    "truck_id": "uuid-or-null"
  }
  ```
- **Side effect:** Simpan JPEG + metadata JSON, kirim webhook ke `palmgrade-api`, push ke `event_queue` untuk WebSocket broadcast.

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
      { "name": "processing", "alive": true }
    ]
  }
  ```

---

### `GET /api/inspection/status`

Info model dan device yang aktif.

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
  │     ├── write_image() JPEG
  │     ├── write_json() _ripeness.json
  │     ├── write_json() _tp.json (if TP)
  │     ├── event_queue.put_nowait()
  │     └── WebhookClient.send() → POST palmgrade-api
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
      {timestamp}_auto.jpg              # Annotated frame buah
      {timestamp}_auto_ripeness.json    # Metadata grading
      {timestamp}_auto_tp.json          # Metadata TP (jika ada)
      {timestamp}_manual.jpg             # Manual capture
      {timestamp}_manual_ripeness.json  # suffix _ripeness wajib — dibaca oleh list_today_results()
  errors/                               # Copy dari semua hasil rej
  logs/
```

`image_url` di response: `captures/results/{date}/{timestamp}_auto.jpg`

FastAPI mount static: `app.mount("/captures", StaticFiles(directory="artifacts"))`

FE akses via: `${LINE_N_URL}/captures/results/{date}/{filename}`

---

## Webhook ke palmgrade-api

Setiap detection final (auto atau manual), kirim POST ke:

```
POST {BACKEND_URL}/api/v1/webhooks/qualitycontrols
```

**Headers:** `x-webhook-secret: {WEBHOOK_SECRET}`, `Content-Type: application/json`

**Payload** — field names dan values HARUS tepat (palmgrade-api validasi strict):
```json
{
  "timestamp": "2026-05-18T10:30:00.123456",
  "image_path": "captures/results/2026-05-18/2026-05-18_103000_auto.jpg",
  "prediction": "Acc",
  "ripeness_status": "ACC",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS",
  "tp_confidence": 0.88,
  "capture_type": "auto",
  "truck_id": "uuid",
  "machine_id": "uuid-dari-tabel-machines",
  "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
}
```

**Kontrak penting:**
- `prediction`: `"Acc"` / `"Rej"` — required, api DTO validate
- `ripeness_status`: `"ACC"` / `"REJ"` UPPERCASE — api DTO `@IsIn(["ACC","REJ","UNKNOWN"])`
- `tp_status`: `"PASS"` / `"FAIL"` / `"UNKNOWN"` atau `null` — BUKAN `"TP"`
- `truck_id`: UUID valid — webhook di-skip kalau `None` (operator belum set truck)
- `machine_id` diisi dari env `MACHINE_ID` — per container berbeda

---

## Environment Variables

| Variable | Default | Keterangan |
|---|---|---|
| `APP_PORT` | `8000` | Port server |
| `APP_HOST` | `0.0.0.0` | Host server |
| `FRONTEND_URL` | `*` | CORS allowed origin |
| `ENABLE_WEBHOOK` | `true` | Toggle webhook |
| `BACKEND_URL` | `http://localhost:2500` | palmgrade-api base URL |
| `WEBHOOK_SECRET` | — | HMAC secret header, harus cocok dengan palmgrade-api |
| `MODEL_FILE` | `best_3class_v2.pt` | Nama file model di `models/release/` |
| `CONF_THRESHOLD` | `0.75` | Minimum confidence YOLO |
| `MINIMUM_SIZE` | `460000` | Minimum area bounding box (px²) — di bawah ini auto rej |
| `CAMERA_TYPE` | `hikrobot` | Sumber kamera: `hikrobot` / `opencv` (webcam atau video file) / `photo` |
| `CAMERA_DEVICE_INDEX` | `0` | Index device webcam (dipakai kalau `CAMERA_TYPE=opencv` tanpa `CAMERA_VIDEO_PATH`) |
| `CAMERA_VIDEO_PATH` | — | Path video file di dalam container (dipakai kalau `CAMERA_TYPE=opencv`) |
| `MACHINE_ID` | — | UUID dari tabel `machines` di PostgreSQL — berbeda per container |
| `CONVEYOR_DIRECTION` | `rtl` | Arah conveyor: `rtl` / `ltr` / `ttb` / `btt` |
| `DETECTION_ENTRY_OFFSET` | `2200` | Jarak (px) dari sisi masuk ke garis deteksi — wajib kalibrasi per kamera |
| `DETECTION_EXIT_OFFSET` | `100` | Jarak (px) dari sisi keluar ke garis exit |
| `ENTRY_MARGIN` | `100` | Toleransi (px) tambahan pada exit check |
| `STREAM_WIDTH` | `1280` | Lebar frame MJPEG stream (setelah resize, sebelum encode) |
| `STREAM_HEIGHT` | `720` | Tinggi frame MJPEG stream |
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
