# Backend Overview — autograde

Rangkuman teknis `autograde` — Python AI camera service untuk sistem grading kelapa sawit.

## Tujuan Project

Menerima feed kamera industri Hikrobot, menjalankan model YOLO secara realtime,
mengklasifikasi kematangan buah sawit (3 kelas), menyimpan hasil inspeksi ke file,
dan mengirimkan event ke `palmgrade-api` lewat **dua jalur**: realtime ke API lokal
(`OutboxRetryWorker`, poll 1 detik) dan **batch tiap jam** ke cloud (`BatchUploadWorker`:
gambar ke Cloudflare R2, teks ke API cloud).

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
autograde/
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
        outbox/                # OutboxStore — antrean realtime ke API lokal
        storage/               # LocalFileStorage (read/write JSON + WebP)
        upload/                # R2Uploader (boto3) + UploadManifest (SQLite state per-item)
        scheduler/             # UploadScheduler — APScheduler cron, tiap jam @ UPLOAD_MINUTE
      workers/                 # Background threads + asyncio tasks
      domain/                  # Business rule murni — tidak ada I/O
      schemas/                 # Pydantic request/response schemas
      core/                    # Config, logging, constants, DI wiring
      license/                 # License guard (Ed25519 JWS, optional)

  images/                      # sample_sawit.jpg — gambar contoh untuk CAMERA_TYPE=photo
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

- **Request body:** `{ "machine_id", "assignment_id", "truck_id", "assigned_at", "ffb_source"?, "plate"? }`
- **Response:** `{ "accepted": true, "machine_id", "truck_id", "assignment_id" }`
- **Side effect:** Set `state.current_truck_id` + `state.current_assignment_id` — semua event selanjutnya punya `assignment_id` ini. `plate` + `assigned_at` juga disimpan, dipakai buat **menamai folder capture** truk itu (`domain/capture_layout.py`).
- ⚠️ `plate` itu **label, bukan identitas** — `truck_id` tetap kunci semua angka. Opsional: konsol lama tidak mengirimnya, dan line yang menolak payload tanpa `plate` akan menghentikan penugasan saat upgrade separuh jalan. Dikirim karena `truck_id` itu uuid5 **dari** plat dan tidak bisa dibalik.

### `POST /internal/manual-reject`

Terima command manual reject dari palmgrade-api. Protected by `x-internal-secret: WEBHOOK_SECRET`.

- **Request body:** `{ "machine_id", "assignment_id", "requested_by", "requested_at" }`
- **Response:** `{ "accepted": true, "message": "capture_reject_requested" }`
- **Side effect:** Trigger `capture_manual_reject()` via `run_in_executor` — WebP + JSON ditulis ke
  `results/{date}/` + satu baris ke `outbox.db` → terkirim ke API lokal dalam ~1 detik, dan ikut
  ter-scan `BatchUploadWorker` ke cloud pada tick berikutnya.

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
- **Side effect:** Simpan WebP + metadata JSON ke `results/{date}/` (inilah yang jadi antrian upload cloud), push ke `event_queue` untuk WebSocket broadcast, dan tulis satu baris ke OutboxStore (antrian realtime ke API lokal).

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
    "plc": {
      "inputs": [false, false, false, false, false, false, false, false, false, false, false],
      "dropped_pulses": 0,
      "dropped_submissions": 0
    },
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

> ⚠️ **Endpoint ini bicara soal jalur realtime lokal saja, bukan cloud:**
>
> | Field | Artinya |
> |---|---|
> | `outbox_pending` / `outbox_failed` | backlog ke **API lokal** (`BACKEND_URL`). Naik terus = API lokal tidak menjawab. **Bukan** indikator backlog upload cloud |
> | `last_successful_api_push` | waktu POST terakhir yang sukses ke API lokal; `null` = belum pernah ada yang terkirim sejak start |
> | `workers[]` | memuat `outbox_retry` dan `plc` (kalau aktif), tapi **tidak** `BatchUploadWorker` — batch upload itu job APScheduler, bukan thread ter-register, jadi **watchdog `_watchdog` tidak memantaunya** |
> | `plc` | `null` kalau `PLC_ENABLED=false` (normal di cloud & PC dev). Kalau terisi: `inputs` (index 0-9 motor fault, index 10 E-stop), plus dua counter drop yang **naik monoton** — yang berarti selisih antar-polling, bukan nilai absolut. Detail: `docs/plc-integration.md` |
>
> Untuk backlog upload sungguhan: query `state/upload_manifest.db` (`SELECT status, COUNT(*) FROM
> upload_items GROUP BY status`) atau baca log worker. Ini gap observability yang belum ditutup.

---

> Info model dan device yang aktif tersedia di `GET /health/detail` (`gpu_available`, `gpu_device`, `camera_type`, dst.) — tidak ada endpoint `/api/inspection/status` terpisah.

---

### `WebSocket /ws/results`

Push event realtime ke client saat ada detection baru. Legacy endpoint — masih aktif tapi FE utama memakai SSE dari `palmgrade-api`.

---

## Console Dev Lanes (`APP_MODE=console`, Task 14)

Surface terpisah dari tabel di atas — berjalan sebagai konsol (`routes/console.py`), bukan `main.py`. Tujuh lane ini melayani lima layar developer (Log, Diagnostik, Antrean ERP, Versi, Uji PLC); semuanya lewat `require_support` dan dijawab **403** kalau operator yang masuk bukan `peran='support'`. Detail rasionalnya: CLAUDE.md, Critical Rule 21.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/console/dev/ping` | cek akses masih hidup, tanpa membaca apa pun |
| GET | `/api/console/dev/log` | `log_kejadian` — filter `level`/`cari`, `limit`+`offset` |
| GET | `/api/console/dev/diagnostik` | `/health/detail` ketiga line, digabung satu jawaban |
| GET | `/api/console/dev/antrean` | `erp_outbox` — jumlah pending/gagal + daftar gagal |
| POST | `/api/console/dev/antrean/kirim-ulang` | requeue semua baris gagal di `erp_outbox` |
| GET | `/api/console/dev/versi` | versi image + status lisensi |
| GET | `/api/console/dev/plc/{line_code}` | snapshot DI + coil yang boleh diuji — baca saja |
| POST | `/api/console/dev/plc/{line_code}/coil` | picu satu coil — satu-satunya lane yang menggerakkan hardware; tiga pengaman (assignment line, konfirmasi ketik, WARNING tiap percobaan) |

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
  │     └── OutboxStore.add_event() — antrean realtime → API lokal (~1 detik)
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
  outbox.db                             # antrean realtime ke API lokal

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

## Event Delivery ke palmgrade-api (dua jalur)

- **Realtime → API lokal.** `OutboxStore.add_event()` dipanggil di jalur deteksi; `OutboxRetryWorker`
  mem-poll tiap 1 detik dan POST ke `BACKEND_URL`. Ini yang dilihat operator di PC pabrik, dan
  satu-satunya jalur yang hidup saat internet mati. `image_path` tetap relatif — api meng-serve
  gambarnya dari mount `artifacts/` read-only.
- **Batch → cloud.** **File hasil deteksi di disk ITU antriannya** (rincian alur dan kelas
  kegagalannya di `docs/overview.md` §4); `BatchUploadWorker` men-scan tiap jam, `PUT` gambar ke R2, lalu POST ke
  `UPLOAD_API_URL`. Lag ke cloud sampai ~1 jam — itu memang desainnya.

`event_id` identik di kedua jalur, jadi tidak ada risiko dobel.

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
- `event_id`: dipakai API untuk idempotency (sparse unique index). uuid5 deterministik dari `machine_id:timestamp` untuk **auto maupun manual** — rumus tunggal di `domain/vision_event.py`; `BatchUploadWorker` menghitungnya ulang dari **nama file** (tidak disimpan di JSON), jadi event yang sudah lewat jalur realtime dibalas `already_processed` waktu batch mengirimnya lagi
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
- ⚠️ **Tidak ditampilkan di `/health/detail`** — `outbox_pending` di sana mengukur jalur realtime
  lokal, tidak ada kaitannya dengan manifest ini

**Catatan operasional:** `outbox.db` dari instalasi lama bisa berisi row pending sisa. Sekarang ada pengirimnya lagi, jadi row itu akan ikut terkirim ke API lokal saat start — `event_id` yang idempoten mencegahnya jadi baris dobel. Kalau isinya sampah tes, kosongkan `artifacts/line-N/outbox.db` sebelum menyalakan.

---

## Environment Variables

| Variable | Default | Keterangan |
|---|---|---|
| `APP_PORT` | `8000` | Port server — di-set docker-compose per line (`8001/8002/8003`), dibaca `entrypoint.sh` + healthcheck. Mengisinya di `.env` tidak berefek |
| `FRONTEND_URL` | `*` | CORS allowed origin |
| `ENABLE_WEBHOOK` | `true` | Toggle webhook |
| `BACKEND_URL` | `http://localhost:2500` | palmgrade-api base URL |
| `BACKEND_API_VER` | `/api/v1` | Prefix versi API untuk canonical events URL |
| `WEBHOOK_SECRET` | — | Shared secret header, harus cocok dengan palmgrade-api |
| `MODEL_FILE` | `best_3class_v2.pt` | Nama file model di `models/release/` |
| `CONF_THRESHOLD` | `0.75` | Minimum confidence YOLO |
| `MINIMUM_SIZE` | `460000` | Minimum area bounding box (px²) — di bawah ini auto rej |
| `CAMERA_TYPE` | `hikrobot` | Sumber kamera: `hikrobot` / `opencv` (webcam atau video file) / `photo` |
| `CAMERA_DEVICE_INDEX` | `0` | Index device webcam (dipakai kalau `CAMERA_TYPE=opencv` tanpa `CAMERA_VIDEO_PATH`). Di-set docker-compose per line (`0/1/2`) — nilai di `.env` hanya berlaku saat run lokal tanpa Docker |
| `CAMERA_VIDEO_PATH` | — | Path video file di dalam container (dipakai kalau `CAMERA_TYPE=opencv`) |
| `CAMERA_VIDEO_LOOP` | `false` | `true` = video diulang terus sampai line di-stop (uji performa); tiap putaran baru me-reset ByteTrack. `false` = diputar sekali lalu capture diam. Tidak berefek ke kamera Hikrobot |
| `CAMERA_PHOTO_PATH` | — | Path image statis di dalam container (wajib kalau `CAMERA_TYPE=photo`). Kosong → `PhotoCamera` raise saat connect |
| `MACHINE_ID` | — | UUID dari tabel `machines` di PostgreSQL — berbeda per container. Di-set docker-compose dari `LINE_{1,2,3}_MACHINE_ID` (fallback UUID seed); `MACHINE_ID` di `.env` hanya untuk run lokal tanpa Docker |
| `ROI_X1` | `0` | Batas kiri area deteksi (px) |
| `ROI_Y1` | `0` | Batas atas area deteksi (px) |
| `ROI_X2` | `0` | Batas kanan area deteksi (px) — `0` = lebar penuh frame |
| `ROI_Y2` | `0` | Batas bawah area deteksi (px) — `0` = tinggi penuh frame |
| `STREAM_WIDTH` | `1280` | Lebar frame MJPEG stream (setelah resize, sebelum encode) |
| `STREAM_HEIGHT` | `720` | Tinggi frame MJPEG stream |
| `STREAM_FPS` | `12` | FPS MJPEG stream — decoupled dari `CAMERA_FPS` |
| `YOLO_SKIP_FRAMES` | `1` | Jalankan YOLO tiap N frame (`1` = produksi; `>1` hemat CPU saat tes video) |
| `DEBUG_MODEL_OUTPUT` | — | Log raw output model tiap inferensi (debug; berisik di produksi) |
| `BORDER_THICKNESS` | `2` | Tebal garis bounding box (px) — naikkan untuk frame sensor 2448×2048 |
| `FONT_SCALE` | `0.7` | Skala teks label deteksi — naikkan untuk frame sensor 2448×2048 |
| `FONT_THICKNESS` | `2` | Tebal teks label deteksi — naikkan untuk frame sensor 2448×2048 |
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
| `LICENSE_ENABLED` | `false` | Aktifkan license guard + gerbang grading |
| `LICENSE_PUBLIC_KEY` | — | Public key Ed25519 untuk verifikasi JWS (nama sama dengan palmgrade-api) |
| `LICENSE_TOKEN` | — | Token langganan; dipasang `palmgrade license <token>`, nempel saat container dibuat ulang |
| `PLC_ENABLED` | `false` | Aktifkan integrasi PLC/ODOT CN-8031. `false` = default, dipakai cloud + semua PC dev — nol thread tambahan, `submit_grading()` langsung `return` |
| `PLC_HOST` | — | IP coupler ODOT. Kosong + `PLC_ENABLED=true` → worker tidak jalan, warning di log |
| `PLC_PORT` | `502` | Port Modbus-TCP |
| `PLC_UNIT_ID` | `1` | Modbus unit/slave ID |
| `PLC_COIL_BASE` | `0` | Literal per line di `docker-compose.yml`, bukan dari `.env` — properti fisik line. Line 1 = `0`, line 2 = `3`, line 3 = `6` |
| `PLC_COIL_ALIVE` | — | Literal per line. Daftar coil dipisah koma yang ditoggle tiap detik. Line 1 = `9,10` (9 = HEARTBEAT PC bersama), line 2 = `11`, line 3 = `12` |
| `PLC_PULSE_MS` | `200` | Lebar pulse ON per keputusan OK/NG — knob tuning lapangan, belum dikonfirmasi PLC engineer |
| `PLC_PULSE_GAP_MS` | `100` | Jeda OFF wajib antar dua pulse pada coil yang sama |
| `PLC_QUEUE_MAX` | `1` | Berapa banyak pulse boleh terutang per coil = **berapa lama sinyal boleh basi** (`queue_max × (pulse+gap)`), bukan kapasitas. Penuh → drop + hitung (`PulseScheduler.dropped`) |
| `PLC_POLL_MS` | `200` | Interval polling `PlcWorker` — sekaligus keepalive watchdog ODOT |
| `PLC_DI_COUNT` | `16` | Jumlah discrete input yang dibaca tiap poll |
| `ERP_ALLOWED_ROLES` | `support` | **Konsol saja.** Peran mana yang boleh datang dari AutoERP (`domain/peran.py`, `saring_peran_erp`). Kosong = tolak semua akun ERP dari lane developer — satu-satunya rem sisi pabrik, tanpa menyentuh AutoERP |
| `LOG_RETENSI_HARI` | `180` | **Konsol saja.** Berapa lama baris `log_kejadian` (ERROR/WARNING, layar Log support) disimpan sebelum dibuang |

> Detail lengkap (coil map, hardware part number, throughput ceiling, open hardware questions): `docs/plc-integration.md`.

---

## Models

| File | Keterangan |
|---|---|
| `models/release/best_3class_v2.pt` | Model utama — deteksi 3 kelas: acc, rej, tp. v2: dataset 2x lebih besar, TP conf lebih stabil |

Model di-load saat startup. Jika file tidak ditemukan, server gagal start.
Model tidak di-commit ke git (ada di `.gitignore` via `*.pt`).
