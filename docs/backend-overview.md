# Backend Overview — palmgrade-vision

Rangkuman teknis `palmgrade-vision` — Python AI camera service untuk sistem grading kelapa sawit.

## Tujuan Project

Menerima feed kamera industri Hikrobot, menjalankan model YOLO secara realtime,
mengklasifikasi kematangan buah sawit (3 kelas), menyimpan hasil inspeksi ke file,
dan mengirimkan event ke `palmgrade-api` lewat **batch upload tiap jam** (`BatchUploadWorker`:
gambar ke Cloudflare R2, teks ke API cloud). Jalur outbox realtime lama sudah di-comment.

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
        outbox/                # OutboxStore — dormant, retry worker di-comment
        storage/               # LocalFileStorage (read/write JSON + WebP)
        upload/                # R2Uploader (boto3) + UploadManifest (SQLite state per-item)
        scheduler/             # UploadScheduler — APScheduler cron, tiap jam @ UPLOAD_MINUTE
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
- **Side effect:** Trigger `capture_manual_reject()` via `run_in_executor` — WebP + JSON ditulis ke
  `results/{date}/`, lalu ikut ter-scan `BatchUploadWorker` pada tick berikutnya (write ke OutboxStore
  sudah di-comment).

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
- **Side effect:** Simpan WebP + metadata JSON ke `results/{date}/` (inilah yang jadi antrian upload), push ke `event_queue` untuk WebSocket broadcast. Write ke OutboxStore sudah di-comment.

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
    ],
    "outbox_pending": 0,
    "outbox_failed": 0,
    "current_assignment_id": "uuid-or-null",
    "last_successful_api_push": null
  }
  ```

> ⚠️ **Endpoint ini tidak lagi memberi tahu apa pun soal pengiriman ke cloud.** Tiga field di bawah
> ini sisa era outbox dan sekarang mati:
>
> | Field | Kondisi sekarang |
> |---|---|
> | `outbox_pending` / `outbox_failed` | **selalu `0`** — tidak ada lagi yang menulis ke outbox, jadi angka 0 di sini **bukan** berarti tidak ada backlog upload |
> | `last_successful_api_push` | **selalu `null`** — hanya pernah di-set `OutboxRetryWorker` (`runtime_state.py:14`), yang sudah di-comment |
> | `workers[]` | tidak memuat `outbox_retry` (registrasinya di-comment di `main.py:150-151`) **maupun** `BatchUploadWorker` — batch upload itu job APScheduler, bukan thread ter-register, jadi **watchdog `_watchdog` tidak memantaunya** |
>
> Untuk backlog upload sungguhan: query `state/upload_manifest.db` (`SELECT status, COUNT(*) FROM
> upload_items GROUP BY status`) atau baca log worker. Ini gap observability yang belum ditutup.

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
  │     └── [DISABLED] OutboxStore.add_event() — di-comment; file di disk ITU antriannya
  └── state.last_yolo_results (read by DisplayWorker)
  ↓ [EventBroadcastWorker — asyncio task]
WebSocket clients

results/{date}/*.webp + *_ripeness.json   ← hasil save di atas
  ↓ [UploadScheduler — APScheduler cron, tiap jam pada menit UPLOAD_MINUTE]
BatchUploadWorker.run_batch_once()
  ├── _scan() → UploadManifest (state/upload_manifest.db)
  ├── PUT gambar → Cloudflare R2
  ├── POST teks  → UPLOAD_API_URL (API cloud), header x-webhook-secret: UPLOAD_API_SECRET
  └── _retention() → hapus file `done` yg lewat UPLOAD_RETENTION_DAYS (default 7)
      ⚠️ bukan thread ter-register → TIDAK dipantau _watchdog

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
  outbox.db                             # outbox lama — dormant (retry worker di-comment)

state/line-N/  ↔ /app/state             # SIBLING artifacts/, sengaja DI LUAR mount /captures
  upload_manifest.db                    # progres BatchUploadWorker (WAL + synchronous=FULL)
```

⚠️ `results/` **bukan arsip permanen** — `_retention()` menghapus WebP + JSON yang `done` dan lewat
`UPLOAD_RETENTION_DAYS` (default 7). Setelah itu satu-satunya salinan gambar ada di R2
(`captures.smagri.id`). Item `poisoned` sengaja tidak ikut dihapus.

`image_url` di response: `captures/results/{date}/{timestamp}_auto.webp`

FastAPI mount static: `app.mount("/captures", StaticFiles(directory="artifacts"))`

FE akses via: `${LINE_N_URL}/captures/results/{date}/{filename}`

---

## Event Delivery ke palmgrade-api (via `BatchUploadWorker`)

Sejak spec batch-upload-r2 (`docs/superpowers/specs/2026-07-10-batch-upload-r2-design.md`),
`OutboxRetryWorker` **di-comment** dan `OutboxStore.add_event()` tidak lagi dipanggil.
**File hasil deteksi di disk sekarang ITU antriannya**; batch worker yang men-scan dan mengirimnya
tiap jam. Konsekuensi operasional: event sampai ke cloud dengan **lag sampai ~1 jam**, bukan
near-real-time.

```
FrameProcessingWorker / CaptureService
    → tulis WebP + {ts}_*_ripeness.json ke artifacts/results/{date}/     ← antriannya
        ↓ [UploadScheduler — APScheduler cron, tiap jam @ UPLOAD_MINUTE]
    BatchUploadWorker.run_batch_once()
        1. _scan()   → UploadManifest.upsert_item()   (idempotent, aman di-scan berulang)
        2. claim     WHERE status IN ('pending','image_uploaded') AND next_retry_at <= now
                     ORDER BY discovered_at ASC  LIMIT UPLOAD_MAX_ITEMS_PER_TICK (2000)
        3. PUT gambar → Cloudflare R2               → mark_image_uploaded()
        4. POST teks  → {upload_events_url}          → mark_done()
                      = {UPLOAD_API_URL}{BACKEND_API_VER}/internal/vision/events
        5. _retention() hapus file `done` yg lewat UPLOAD_RETENTION_DAYS
```

**Headers:** `x-webhook-secret: {UPLOAD_API_SECRET}`, `Content-Type: application/json`

> ⚠️ **Jangan tertukar dua pasang variabel ini.** `BACKEND_URL` + `WEBHOOK_SECRET` = API **lokal**
> (webhook realtime, tidak berubah). `UPLOAD_API_URL` + `UPLOAD_API_SECRET` = API **cloud**, dan
> hanya inilah yang dipakai batch worker. `UPLOAD_API_SECRET` isinya `WEBHOOK_SECRET` milik API
> cloud. **`R2_BUCKET` kosong = batch jadi no-op** — cuma `logger.warning` sekali lalu diam.

**Payload** — field names dan values HARUS tepat:
```json
{
  "event_id": "uuid",
  "assignment_id": "uuid",
  "machine_id": "uuid-dari-tabel-machines",
  "truck_id": "uuid-or-null",
  "timestamp": "2026-05-18T10:30:00.123456+00:00",
  "image_path": "https://captures.smagri.id/{machine_id}/2026-05-18/2026-05-18_103000_auto.webp",
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
- `event_id`: dipakai API untuk idempotency (sparse unique index). **Auto** = uuid5 deterministik dari `machine_id:timestamp` — dihitung `BatchUploadWorker` dari **nama file**, bukan disimpan di JSON. Formulanya **sengaja identik** dengan outbox lama, jadi event yang sudah terkirim di era outbox tidak dobel kalau file-nya ikut ter-scan; **manual** = uuid4
- `timestamp`: ISO-8601 **UTC-aware** (`datetime.now(timezone.utc)`)
- `assignment_id`: dari `state.current_assignment_id` — set saat `/internal/assignment` dipanggil. Key-nya **di-omit** kalau meta tidak punya nilainya (bukan dikirim `null`)
- `image_path`: **URL absolut R2** (`{R2_PUBLIC_URL}/{r2_key}`), bukan path relatif. `r2_key` diprefix `machine_id` supaya antar-line terisolasi. Gambar di-PUT duluan; POST baru jalan setelah PUT sukses
- `prediction`: `"Acc"` / `"Rej"` — required
- `ripeness_status`: `"ACC"` / `"REJ"` UPPERCASE
- `tp_status`: `"PASS"` / `null` — BUKAN `"TP"`
- `truck_id`: boleh `null`. **PERUBAHAN PERILAKU vs era outbox:** `_scan()` **tidak** memfilter truck, jadi deteksi auto tanpa truck aktif **ikut ter-upload** dengan `truck_id: null` — dulu event begitu di-skip. API tetap menyimpan event, truck fields di MongoDB null.
- API returns `{status: "already_processed"}` jika `event_id` duplikat — worker anggap sukses, `mark_done()`

**`UploadManifest` (`state/upload_manifest.db`):**
- State per item: `pending` → `image_uploaded` → `done` (+ `poisoned` untuk input cacat)
- Exponential backoff: 5s base, 600s cap — **TANPA retry cap, TANPA TTL** (beda kontrak dari outbox
  lama yang dead-letter setelah 50 retry). Item menunggu selamanya sampai terkirim, sesuai syarat
  "tahan outage berapa lama pun, nol data hilang, nol duplikat"
- Durability: WAL + `synchronous=FULL` — sama persis dengan `outbox_store.py`
- Penanganan kegagalan: `_PoisonError` → `mark_poisoned` + **continue** (file tidak dihapus, sengaja
  ditinggal untuk diperiksa); `_RequeueError(batch_fatal=False)` untuk HTTP 404 → requeue +
  **continue** (antrian `ORDER BY discovered_at ASC`, tanpa ini satu item lama bisa head-of-line
  starve seluruh batch); `_RequeueError` default → requeue + **break batch**
- ⚠️ **Tidak ditampilkan di `/health/detail`** — `outbox_pending` di sana selalu 0 dan tidak ada
  kaitannya dengan manifest ini

**Catatan operasional:** `outbox.db` lama bisa berisi row pending sisa — inert (tidak ada pengirim); backfill batch meng-cover file yang sama via manifest, dan `event_id` idempoten mencegah dobel kalau outbox di-uncomment lagi.

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
| `UPLOAD_MINUTE` | `0` | Menit tiap jam batch uploader jalan |
| `UPLOAD_MAX_ITEMS_PER_TICK` | `2000` | Jumlah maksimal item per batch run |
| `UPLOAD_RETENTION_DAYS` | `7` | Hari retensi manifest SQLite |
| `R2_ACCOUNT_ID` | — | Cloudflare R2 account ID (placeholder — kosong = no-op) |
| `R2_ACCESS_KEY_ID` | — | Cloudflare R2 access key ID (placeholder — kosong = no-op) |
| `R2_SECRET_ACCESS_KEY` | — | Cloudflare R2 secret access key (placeholder — kosong = no-op) |
| `R2_BUCKET` | — | Cloudflare R2 bucket name (kosong = no-op) |
| `R2_PUBLIC_URL` | — | Cloudflare R2 public URL prefix (placeholder — kosong = no-op) |
| `UPLOAD_API_URL` | — | Base URL API cloud untuk batch events |
| `UPLOAD_API_SECRET` | — | WEBHOOK_SECRET API cloud |
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
