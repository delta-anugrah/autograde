# Backend Overview — ripe-recognition-main

Dokumen ini adalah rangkuman menyeluruh tentang project `ripe-recognition-main`
sebagai Python backend untuk sistem inspeksi kematangan sawit.

## Tujuan Project

Menerima feed kamera industri (Hikrobot), menjalankan model YOLO secara
realtime, mengklasifikasi kematangan buah sawit, menyimpan hasil inspeksi, dan
mengirimkan webhook ke Node.js API.

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| Framework | FastAPI |
| Server | Uvicorn |
| Model inference | Ultralytics YOLO |
| Computer vision | OpenCV |
| Deep learning | PyTorch |
| Camera SDK | MvImport (Hikrobot proprietary) |
| HTTP client | httpx (async) |
| Scheduler | APScheduler |
| Config | python-dotenv + dataclass |
| Validasi schema | Pydantic |

---

## Folder Structure

```
ripe-recognition-main/
  src/
    ripe_recognition/
      main.py                  # FastAPI app factory + middleware + lifecycle

      routes/                  # Hanya deklarasi endpoint dan router wiring
      controllers/             # Terima request, panggil service, return response
      services/                # Orchestration dan business flow
      repositories/            # Baca/tulis persistence (file JSON, state)
      pipelines/               # Logic YOLO inference dan frame processing
      integrations/
        camera/                # Abstraksi kamera (base + Hikrobot + OpenCV)
        notifications/         # Webhook client (httpx)
        storage/               # Read/write file lokal (JSON, JPEG)
        scheduler/             # APScheduler untuk upload otomatis
      workers/                 # Background thread loops + runtime state
      domain/                  # Business rule murni (voting, PASS/FAIL)
      schemas/                 # Pydantic request/response schemas
      core/                    # Config, logging, constants, exceptions, DI

  cli/                         # Script CLI untuk training dan predict offline
  models/
    release/                   # Model .pt yang dipakai di produksi
    experiments/               # Model eksperimen / training output
  artifacts/
    captures/                  # Metadata JSON dari manual capture
    results/                   # Metadata JSON + JPEG dari auto detection
    logs/                      # Log file
  tests/
    unit/
    integration/
  docs/
```

---

## Layer Responsibilities

| Layer | Boleh | Tidak Boleh |
|---|---|---|
| `routes/` | Deklarasi endpoint, include controller | Logic apapun |
| `controllers/` | Terima request, return response | Query DB, panggil model |
| `services/` | Orchestrasi, gabungkan repo + pipeline | Query langsung, detail SDK |
| `repositories/` | Baca/tulis file/state | Business rule, HTTP call |
| `pipelines/` | YOLO inference, frame processing | HTTP, persistence |
| `integrations/` | Akses sistem eksternal | Business rule |
| `workers/` | Background loop, queue runtime | HTTP handler |
| `domain/` | Pure business rule (voting, status) | Semua I/O |

---

## API Endpoints

### `GET /api/video_feed`

Streaming kamera realtime dalam format MJPEG.

- **Response:** `StreamingResponse` dengan `Content-Type: multipart/x-mixed-replace; boundary=frame`
- **Consumed by FE:** `<img src="${SAWIT_API_URL}/api/video_feed" />` di
  [quality-control-list.tsx](../../supplier-dashboard/src/modules/quality-control/list/quality-control-list.tsx)
- **Headers wajib:**
  ```
  Cache-Control: no-cache, no-store, must-revalidate
  Connection: close
  ```

---

### `GET /api/results_today`

Mengembalikan semua hasil inspeksi hari ini dari folder results.

- **Response:**
  ```json
  [
    {
      "id": "2024-01-15_120000_000000",
      "status": "PASS | FAIL",
      "title": "PASS Detected",
      "description": "Prediction=Acc (conf=0.95, truck_id=TRK-001)",
      "timestamp": "2024-01-15T12:00:00.000000",
      "image_url": "captures/results/2024-01-15/2024-01-15_120000_000000_auto.jpg",
      "capture_type": "auto | manual",
      "truck_id": "TRK-001",
      "bounding_box": { "x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100 },
      "trunk_box": { "label": "Acc", "score": 0.91, "x_min": 10, "y_min": 10, "x_max": 90, "y_max": 90 }
    }
  ]
  ```
- **Catatan:** Data dibaca dari file `.json` di `artifacts/results/{YYYY-MM-DD}/`.

---

### `POST /api/set_truck`

Set truck ID yang sedang aktif dipantau.

- **Request body:**
  ```json
  { "truck_id": "TRK-001" }
  ```
- **Response:**
  ```json
  { "message": "Truck ID set", "truck_id": "TRK-001" }
  ```
- **Side effect:** Menyimpan `current_truck_id` ke `RuntimeState`. Semua
  hasil auto detection setelah ini akan ter-tag dengan truck_id ini.

---

### `POST /api/capture_reject`

Manual capture frame saat ini dan langsung mark sebagai FAIL.

- **Request body:** Tidak ada.
- **Response:**
  ```json
  {
    "id": "2024-01-15_120000_000000",
    "status": "FAIL",
    "title": "FAIL Detected (Manual)",
    "description": "Prediction=Rej (conf=1.00, manual capture)",
    "timestamp": "2024-01-15T12:00:00.000000",
    "image_url": "captures/results/2024-01-15/2024-01-15_120000_000000_manual.jpg",
    "capture_type": "manual",
    "truck_id": "TRK-001",
    "prediction": "Rej",
    "confidence": 1.0
  }
  ```
- **Side effect:** Simpan JPEG + metadata JSON, kirim webhook ke Node.js API,
  push event ke `event_queue` untuk WebSocket broadcast.

---

### `WebSocket /ws/results`

Push event realtime ke client saat ada hasil detection baru.

- **Event payload:**
  ```json
  {
    "id": "2024-01-15_120000_000000",
    "status": "PASS | FAIL",
    "title": "PASS Detected",
    "description": "...",
    "timestamp": "...",
    "image_url": "captures/results/...",
    "capture_type": "auto | manual",
    "truck_id": "TRK-001"
  }
  ```
- **Catatan:** WebSocket ini opsional. FE saat ini lebih menggunakan SSE dari
  Node.js API untuk real-time update. WebSocket ini bisa dipertahankan sebagai
  fallback atau untuk debugging.

---

## Realtime Processing Flow

```
Kamera (Hikrobot)
  ↓ [FrameCaptureWorker — daemon thread]
frame_queue
  ↓ [FrameProcessingWorker — daemon thread]
  ├── YOLO track() → detect bounding box + track_id
  ├── VoteTracker.register(label) → akumulasi vote per track_id
  ├── derive_status(label) → "PASS" atau "FAIL"
  ├── [jika vote tembus threshold]
  │     ├── LocalFileStorage.write_image() → simpan JPEG
  │     ├── LocalFileStorage.write_json() → simpan metadata
  │     ├── event_queue.put(event)
  │     └── WebhookClient.send_quality_event() → POST ke Node.js
  └── encode frame → result_queue
  ↓ [EventBroadcastWorker — asyncio task]
WebSocket clients
  ↓ [generate_frames()]
MJPEG stream → FE
```

---

## Domain Logic

### VoteTracker (`domain/voting.py`)

Setiap buah sawit di-track via YOLO track_id. Setiap frame, label detection
di-register ke tracker. Jika label konsisten mencapai `VOTE_THRESHOLD` frame,
hasilnya dianggap final.

```
frame 1: Acc → votes=1
frame 2: Acc → votes=2
frame 3: Acc → votes=3  ← tembus VOTE_THRESHOLD (default=3) → FINAL
frame 4: (sudah di-skip karena processed=True)
```

Jika label berubah sebelum tembus threshold, vote direset dari 0.

### Status Rule (`domain/rules.py`)

```python
derive_status("Rej")   → "FAIL"
derive_status("reject") → "FAIL"
derive_status("Acc")   → "PASS"
```

---

## File & Path Conventions

### Penyimpanan hasil detection

```
artifacts/
  results/
    {YYYY-MM-DD}/
      {timestamp}_auto.jpg    # Annotated frame
      {timestamp}_auto.json   # Metadata
      {timestamp}_manual.jpg  # Manual capture
      {timestamp}_manual.json
  captures/
    {YYYY-MM-DD}/
      {timestamp}.json        # Metadata dari manual capture
```

### image_url format di response

```
captures/results/2024-01-15/2024-01-15_120000_000000_auto.jpg
```

URL ini diakses oleh FE dengan prefix `NEXT_PUBLIC_SAWIT_API_URL`:
```
http://localhost:8000/captures/results/2024-01-15/...jpg
```

Artinya FastAPI harus mount static files:
```python
app.mount("/captures", StaticFiles(directory="artifacts"), name="captures")
```

---

## Webhook ke Node.js API

Setiap ada detection final (auto maupun manual), BE mengirim POST request ke:

```
POST {BACKEND_URL}{BACKEND_API_VER}/webhooks/qualitycontrols
```

Default: `http://localhost:2500/api/v1/webhooks/qualitycontrols`

**Headers:**
```
Content-Type: application/json
x-webhook-secret: {WEBHOOK_SECRET}
```

**Payload:**
```json
{
  "timestamp": "2024-01-15T12:00:00",
  "image_path": "captures/results/2024-01-15/..._auto.jpg",
  "prediction": "Acc | Rej",
  "confidence": 0.95,
  "status": "PASS | FAIL",
  "capture_type": "auto | manual",
  "truck_id": "TRK-001",
  "bounding_box": { "x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100 },
  "trunk_box": { "label": "Acc", "score": 0.91, ... }
}
```

---

## Environment Variables

| Variable | Default | Keterangan |
|---|---|---|
| `RUNNING_PORT` | `8000` | Port server |
| `APP_HOST` | `0.0.0.0` | Host server |
| `FRONTEND_URL` | `*` | CORS allowed origin |
| `ENABLE_WEBHOOK` | `true` | Toggle webhook |
| `BACKEND_URL` | `http://localhost:2500` | Node.js API URL |
| `BACKEND_API_VER` | `/api/v1` | Node.js API version prefix |
| `WEBHOOK_SECRET` | `supersecret123` | Secret header untuk webhook |
| `MODEL_SIZE` | `n` | Ukuran YOLO detection model |
| `MODEL_VERSION` | `det_v1` | Versi YOLO detection model |
| `CLS_MODEL_SIZE` | `m` | Ukuran YOLO classify model |
| `CLS_MODEL_VERSION` | `cls_v1` | Versi YOLO classify model |
| `CONF_THRESHOLD` | `0.75` | Minimum confidence YOLO |
| `VOTE_THRESHOLD` | `3` | Jumlah frame konsisten untuk final result |
| `CAMERA_WIDTH` | `320` | Resolusi kamera (width) |
| `CAMERA_HEIGHT` | `240` | Resolusi kamera (height) |
| `CAMERA_FPS` | `30` | Target FPS kamera |
| `BORDER_THICKNESS` | `2` | Tebal border bounding box |
| `FONT_SCALE` | `0.7` | Ukuran font label |
| `FONT_THICKNESS` | `2` | Tebal font label |
| `ROI_SCALE` | `0.7` | Skala ROI |
| `UPLOAD_HOUR` | `0` | Jam upload otomatis (cron) |
| `UPLOAD_MINUTE` | `0` | Menit upload otomatis (cron) |
| `DESTINATION_UPLOAD` | - | Path tujuan upload hasil |

---

## Models

| File | Deskripsi |
|---|---|
| `models/release/classify_and_detect.pt` | Model utama: deteksi + klasifikasi kematangan |
| `models/release/tangkai_sawit.pt` | Model deteksi tangkai/batang |

Kedua model di-load saat startup. Jika file tidak ditemukan, server gagal start.

---

## Migration Status

Lihat [migration-progress.md](./migration-progress.md) untuk status terkini.

Singkatnya:
- Skeleton folder dan routing: selesai
- Core config, domain rules, storage: sebagian besar selesai
- Camera SDK, webhook, pipeline YOLO, workers, main wiring: belum diimplementasi
