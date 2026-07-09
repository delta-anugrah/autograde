# palmgrade-vision

AI camera service for the **Palmgrade** palm oil ripeness grading system.

Runs as **3 separate Docker containers** (one per camera line), each connected to a Hikrobot industrial camera. Performs real-time YOLO-based fruit ripeness detection and pushes results to `palmgrade-api` via durable outbox delivery.

---

## Part of the Palmgrade System

| Repo | Role | Port |
|---|---|---|
| **`palmgrade-vision`** | AI camera + inference | 8001 / 8002 / 8003 |
| `palmgrade-api` | Business logic, auth, SSE broker | 2500 |
| `palmgrade-frontend` | Operator dashboard UI | 3050 |

> Full system architecture: see [`ARCHITECTURE.md`](../ARCHITECTURE.md)

---

## How It Works

```
Camera (Hikrobot / OpenCV / Photo)
    → FrameCaptureWorker  (thread) → frame_queue
    → FrameProcessingWorker (thread)
        → YOLOv8 + ByteTrack
        → detect: acc / rej / tp (tangkai panjang)
        → save WebP + JSON to artifacts/results/
        → OutboxStore.add_event()  ← durable SQLite write
    → OutboxRetryWorker (daemon thread)
        → POST /api/v1/internal/vision/events → palmgrade-api
    → StreamingService
        → MJPEG /api/video_feed (multi-viewer via Condition broadcast)

palmgrade-api → POST /internal/assignment → update state.current_truck_id + assignment_id
palmgrade-api → POST /internal/manual-reject → trigger capture_manual_reject()
```

**Detection model**: `best_3class_v2.pt` — 3 classes: `acc` (accepted), `rej` (rejected), `tp` (long stalk)
**Minimum size**: 460,000 px² — objects below this area are forced to `rej`
**Tracking**: ByteTrack — each fruit gets a unique `track_id`, saved only once (single-trigger)
**Detection zone**: ROI box (`ROI_X1/Y1/X2/Y2`) — only objects whose center falls inside the box are counted. Default `0,0,0,0` = full frame. TP class is exempt from ROI check.
**Multi-fruit rule**: >1 buah (belum diproses) berada dalam ROI di frame yang sama → semuanya di-force `rej` (buah bertumpuk).

---

## Prerequisites

- Docker & Docker Compose
- `make` (GNU Make)
- Hikrobot MVS SDK installed at `/opt/MVS/` on the host — `make up` auto-copies all required libs
- NVIDIA Container Toolkit — untuk GPU passthrough ke Docker (lihat [Production Deployment](#production-deployment-pindah-ke-pc-baru))
- YOLO model file at `models/release/best_3class_v2.pt`

> **No local Python/venv needed** — semua dijalankan via Docker. `python:3.11-slim` base image sudah include semua dependencies.

---

## Project Structure

```
palmgrade-vision/
├── src/palmgrade/
│   ├── main.py                  # FastAPI app entry point (lifespan)
│   ├── core/                    # Config, logging, DI wiring
│   ├── routes/                  # FastAPI routers
│   ├── controllers/             # Request handlers
│   ├── services/                # Business logic
│   ├── repositories/            # File I/O (JPEG, JSON)
│   ├── pipelines/               # YOLO inference + frame processing
│   ├── workers/                 # Background threads & asyncio tasks
│   ├── integrations/
│   │   ├── camera/              # HikrobotCamera / OpenCVCamera / PhotoCamera
│   │   ├── notifications/       # WebhookClient (httpx)
│   │   ├── storage/             # LocalFileStorage
│   │   └── scheduler/           # APScheduler daily upload cron
│   ├── domain/                  # Pure business rules (no I/O)
│   ├── schemas/                 # Pydantic request/response models
│   └── license/                 # License guard (Ed25519 JWS, optional)
├── models/
│   └── release/
│       └── best_3class_v2.pt    # YOLO model — required, not committed to git
├── artifacts/                   # Runtime output — not committed to git
│   ├── line-1/
│   ├── line-2/
│   └── line-3/
├── Makefile
├── Dockerfile
├── docker-compose.yml           # 3 services: line-1 (8001), line-2 (8002), line-3 (8003)
├── requirements.txt
├── .env                         # Local env (copy from .env.example)
└── .env.example
```

---

## Setup

### 1. Clone & copy env

```bash
git clone git@github.com:delta-anugrah/palmgrade-vision.git
cd palmgrade-vision
cp .env.example .env
```

### 2. Edit `.env`

Key variables to fill in:

```env
# Kamera — pilih sesuai environment
CAMERA_TYPE=hikrobot        # hikrobot | opencv | photo
CAMERA_VIDEO_PATH=          # isi path video kalau CAMERA_TYPE=opencv dan mau pakai video file
CAMERA_PHOTO_PATH=          # wajib kalau CAMERA_TYPE=photo

# Backend (palmgrade-api)
BACKEND_URL=http://localhost:2500
WEBHOOK_SECRET=your-webhook-secret   # wajib ganti dari default!

# Machine UUIDs — must match machines.id in PostgreSQL (palmgrade-api)
LINE_1_MACHINE_ID=<uuid-from-db>
LINE_2_MACHINE_ID=<uuid-from-db>
LINE_3_MACHINE_ID=<uuid-from-db>

# Model
MODEL_FILE=best_3class_v2.pt
CONF_THRESHOLD=0.75
MINIMUM_SIZE=460000

# Stream (MJPEG — tidak mempengaruhi hasil simpan)
STREAM_WIDTH=1280
STREAM_HEIGHT=720
```

### 3. Place the model file

```bash
mkdir -p models/release
# copy best_3class_v2.pt ke models/release/
```

### 4. Siapkan Hikrobot SDK (production only)

Install Hikrobot MVS SDK di host (`/opt/MVS/`). `make up` akan otomatis copy **seluruh** `/opt/MVS/lib/64/` (termasuk GigE transport layer) ke `sdk/lib64/` dan include ke Docker image.

> Lihat panduan lengkap: [`docs/SETUP.md`](docs/SETUP.md)

---

## Production Deployment (Pindah ke PC Baru)

Checklist lengkap sebelum `make up` di PC produksi. Urutan ini penting.

### 1. Install NVIDIA Container Toolkit

Wajib untuk GPU passthrough ke Docker. Tanpa ini `torch.cuda.is_available()` selalu `False` di dalam container dan YOLO jalan di CPU (10x lebih lambat).

```bash
# Tambah repo NVIDIA
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

Verifikasi:
```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

### 2. Siapkan Hikrobot SDK

Install Hikrobot MVS SDK di host (`/opt/MVS/`). `make up` otomatis copy **seluruh** `/opt/MVS/lib/64/` ke `sdk/lib64/` dan include ke Docker image — tidak perlu copy manual.

> Panduan instalasi MVS lengkap: [`docs/SETUP.md § 3`](docs/SETUP.md)

### 3. Place YOLO model

```bash
mkdir -p models/release
# copy best_3class_v2.pt ke models/release/
```

### 4. Configure `.env`

```bash
cp .env.production .env   # template prod siap-copas (APP_ENV=production, DEBUG off, secret placeholder)
# atau: cp .env.example .env   (template minimal buat dev)
# Wajib diisi:
# LINE_1_MACHINE_ID=<uuid>   — UUID dari tabel machines di PostgreSQL (palmgrade-api)
# LINE_2_MACHINE_ID=<uuid>
# LINE_3_MACHINE_ID=<uuid>
# BACKEND_URL=http://<ip>:2500
# WEBHOOK_SECRET=<sama dengan palmgrade-api>
# CAMERA_TYPE=hikrobot
# CAMERA_FPS=10   — samakan dengan Acquisition Frame Rate kamera (docs/SETUP.md § 6.3)
```

### 5. Build GPU image & run

```bash
# Build GPU image + copy SDK + start semua 3 line (~2.4GB download torch, ~30 menit)
make up

# Verifikasi GPU aktif
curl http://localhost:8001/health/detail | grep gpu_available
# Expected: "gpu_available": true
```

> **Download torch+cu126** langsung dari `download.pytorch.org/whl/cu126`.
> `PIP_RETRIES=10` sudah di-set di Dockerfile — auto-retry kalau koneksi putus.
> Setelah selesai jalankan `docker image prune -f` untuk bersihkan layer yang jadi dangling.

---

## Running

### Semua command via `make`

```bash
make up          # production: copy SDK dari /opt/MVS/, build GPU+SDK, start semua line
make up-dev      # development: build CPU tanpa SDK, start semua line
make start       # start semua line tanpa rebuild (pakai image yang sudah ada)
make restart     # restart semua container — cukup untuk perubahan KODE (bind-mount .:/app)
make up-1        # start line-1 saja tanpa rebuild
make up-2        # start line-2 saja tanpa rebuild
make up-3        # start line-3 saja tanpa rebuild
make down        # stop semua
make logs        # tail logs gabungan semua line
make logs-1      # tail logs line-1 saja
make logs-2      # tail logs line-2 saja
make logs-3      # tail logs line-3 saja
make ps          # status semua container
make rebuild     # rebuild image GPU/CUDA (tanpa SDK, tanpa start) — selalu GPU
make rebuild-gpu # sama dengan make rebuild (alias, untuk kompatibilitas)
make rebuild-clean # full rebuild --no-cache (hanya kalau cache dicurigai rusak — lambat)
make build-engine  # build TensorRT FP16 engine (SEMENTARA NONAKTIF — lihat catatan di bawah)
make clean       # down + hapus image lokal
```

> **Satu image, tiga container** — hanya line-1 yang punya `build:` di docker-compose. Line-2 dan line-3 reuse image `palmgrade-vision:latest`. Jadi `make rebuild` cukup untuk update semua line (tinggal `make start` setelahnya).
>
> **`make rebuild` selalu GPU** — tidak ada variant CPU untuk rebuild. Jika ingin build CPU (khusus dev tanpa GPU), gunakan `make up-dev`.

> **Hot-reload** — source code di-mount via `.:/app`. Perubahan Python langsung terdeteksi tanpa rebuild image (saat `APP_ENV=development`). Di production cukup `make restart` untuk perubahan kode — `make up` hanya perlu kalau dependency / `Dockerfile` / SDK berubah.

> **TensorRT (sementara nonaktif)** — install TensorRT di `Dockerfile` dan step `build-engine` di `make up` sedang di-comment (disk dev PC penuh saat unpack). Runtime otomatis **fallback ke model `.pt`** (`pipelines/model_registry.py`) — fungsional sama, hanya lebih lambat. Di PC prod: uncomment blok TensorRT di `Dockerfile` + `$(MAKE) build-engine` di `Makefile`, rebuild, lalu `make build-engine`.

> **Video file** — kalau `CAMERA_TYPE=opencv` dan `CAMERA_VIDEO_PATH` diisi, path harus di dalam container. Semua 3 line sudah di-mount `/home/nexio/Desktop/Projects/sawit:/videos:ro`. Gunakan `CAMERA_VIDEO_PATH=/videos/namafile.mp4`.

### Container per line

| Container | Port | Camera Index | Machine ID env |
|---|---|---|---|
| `ripe_line_1` | 8001 | 0 | `LINE_1_MACHINE_ID` |
| `ripe_line_2` | 8002 | 1 | `LINE_2_MACHINE_ID` |
| `ripe_line_3` | 8003 | 2 | `LINE_3_MACHINE_ID` |

### Camera type (dikontrol via env var `CAMERA_TYPE`)

| `CAMERA_TYPE` | Source | Dikontrol oleh |
|---|---|---|
| `hikrobot` | Kamera industrial Hikrobot via **RJ45 LAN** (GigE Vision) | `CAMERA_DEVICE_INDEX` |
| `opencv` | Webcam **atau** video file | `CAMERA_VIDEO_PATH` (jika diisi) → video file; jika kosong → webcam via `CAMERA_DEVICE_INDEX` |
| `photo` | Gambar statis, di-loop terus | `CAMERA_PHOTO_PATH` |

`opencv` menggunakan `cv2.VideoCapture()` yang bisa terima `int` (webcam index) maupun `str` (path file video) — satu class, dua source.

**Tidak perlu edit kode** saat switch environment — cukup ubah env var di `.env`.

**Hikrobot (GigE Vision) di Docker** — kamera terhubung via RJ45 LAN, bukan USB. Docker-compose sudah dikonfigurasi dengan `network_mode: host` sehingga container bisa langsung discover kamera via UDP broadcast. Tidak perlu konfigurasi tambahan selain pastikan kamera dan host ada di subnet yang sama.

**Graceful startup** — app tetap jalan meskipun kamera belum terhubung saat startup. `health.detail.camera_connected` akan `false`, dan `FrameCaptureWorker` otomatis retry sampai kamera terdeteksi. Begitu kamera dicolok (dan MVS di-close), `camera_connected` berubah jadi `true` tanpa restart container.

**MJPEG stream** — default encode di 1280×720 (dikontrol via `STREAM_WIDTH`/`STREAM_HEIGHT`). Frame asli Hikrobot 4K tetap disimpan ke disk; resize hanya untuk stream.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check (always allowed) |
| `GET` | `/health/detail` | Detailed status: camera, GPU, workers, outbox_pending, current_assignment_id |
| `GET` | `/api/video_feed` | MJPEG live stream (multi-viewer) |
| `POST` | `/api/set_truck` | Set active truck ID (legacy — prefer API /grading-console/lines/:id/assign-truck) |
| `POST` | `/api/capture_reject` | Trigger manual reject capture (legacy) |
| `GET` | `/api/results_today` | Today's grading results (model/device info ada di `/health/detail`) |
| `POST` | `/internal/assignment` | Receive truck assignment from palmgrade-api (protected by x-internal-secret) |
| `POST` | `/internal/manual-reject` | Receive manual reject command from palmgrade-api (protected by x-internal-secret) |
| `WS` | `/ws/results` | WebSocket result push (legacy) |
| `GET` | `/captures/results/...` | Static files — saved result images |

```bash
# Health check
curl http://localhost:8001/health

# Set truck
curl -X POST http://localhost:8001/api/set_truck \
  -H "Content-Type: application/json" \
  -d '{"truck_id": "your-truck-uuid"}'
```

---

## Event Payload (sent to palmgrade-api via OutboxRetryWorker)

Events are written to `OutboxStore` (SQLite) first, then delivered asynchronously to `POST /api/v1/internal/vision/events`.

```json
{
  "event_id": "uuid",
  "assignment_id": "uuid-or-null",
  "machine_id": "uuid-from-machines-table",
  "truck_id": "uuid-or-null",
  "timestamp": "2026-05-18T10:30:00.123456+00:00",
  "image_path": "captures/results/2026-05-18/2026-05-18_103000_123456_auto.webp",
  "prediction": "Acc",
  "ripeness_status": "ACC",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS",
  "tp_confidence": 0.88,
  "capture_type": "auto",
  "bounding_box": { "x_min": 100, "y_min": 80, "x_max": 420, "y_max": 380 }
}
```

**Field contracts:**
- `event_id`: UUID — used by API for idempotency. **Auto detection** = uuid5 deterministik (`machine_id:timestamp`) supaya re-process setelah crash menghasilkan `event_id` sama (no double count); **manual reject** = uuid4
- `timestamp`: ISO-8601 **UTC-aware** (`datetime.now(timezone.utc)`)
- `prediction`: `"Acc"` / `"Rej"` — required
- `ripeness_status`: `"ACC"` / `"REJ"` UPPERCASE
- `tp_status`: `"PASS"` atau `null` — bukan `"TP"`
- `truck_id`: **auto detection** hanya dikirim ke API kalau ada truck aktif (tanpa truck event di-skip dari outbox, tapi tetap disimpan ke disk). **Manual reject** selalu dikirim, `truck_id` boleh `null` — API tetap menyimpan event, truck fields di MongoDB null
- Events survive restart — stored in `artifacts/outbox.db` per container

---

## Artifact Output

```
artifacts/line-1/
├── results/                   # Satu-satunya sumber kebenaran (auto + manual)
│   └── 2026-05-18/
│       ├── 2026-05-18_103000_auto.webp               # Fruit image (WebP, quality 65)
│       ├── 2026-05-18_103000_auto_ripeness.json      # Detection metadata
│       ├── 2026-05-18_103000_auto_tp.json            # Long stalk metadata (if detected)
│       ├── 2026-05-18_104500_manual.webp             # Manual reject capture
│       └── 2026-05-18_104500_manual_ripeness.json
├── logs/
└── outbox.db                  # SQLite durable outbox
```

> Folder `captures/` dan `errors/` masih dibuat saat startup tapi **tidak ditulis lagi** — manual reject disimpan ke `results/`, dan foto REJ ditemukan via metadata (`ripeness_status: "REJ"`), bukan salinan terpisah.

Images are served as static files: `GET /captures/results/{date}/{filename}`

---

## License Guard (optional, disabled by default)

```env
LIC_ENABLED=true
LIC_SERVER_URL=https://your-license-server.com
LIC_API_KEY=your-api-key
LIC_PUBKEY_PEM=-----BEGIN PUBLIC KEY-----\nMCow...\n-----END PUBLIC KEY-----
```

When enabled, all routes (except `/health`, `/api/video_feed`, `/captures`) are blocked for expired licenses.

---

## Testing

Unit test di sini **sengaja murni-logic** — tidak butuh torch / OpenCV / MVS SDK / GPU, jadi cepat dan jalan di runner CI ringan. Pengujian yang butuh hardware/model asli (inference YOLO, kamera fisik) adalah ranah **integration test** di Docker (`tests/integration/`, masih `.gitkeep`), bukan unit test.

### Menjalankan test

Dari `palmgrade-vision/`:

```bash
# CI menjalankan keduanya (lihat .github/workflows/ci.yml)
pip install ruff pytest cryptography aiosqlite psutil httpx
ruff check tests/ src/palmgrade/domain/ src/palmgrade/integrations/outbox/ src/palmgrade/license/
pytest tests/unit/
```

> Konfigurasi pytest ada di `pyproject.toml` (`pythonpath=["src"]`) — tidak perlu set `PYTHONPATH` manual. Tidak memakai `pytest-asyncio`: kode async diuji lewat `asyncio.run` stdlib supaya dependency CI minimal.

### Cakupan (`tests/unit/`)

| Area | File | Yang dikunci |
|---|---|---|
| Domain rules | `test_rules.py` | Klasifikasi ripeness (inti keputusan bisnis) |
| Idempotency | `test_event_id.py` | `event_id` uuid5 deterministik (anti double-count) |
| Outbox durable | `test_outbox_store.py`, `test_outbox_requeue.py` | Persist → backoff → dead-letter (jaminan delivery ke API) |
| Config | `test_config_validation.py` | Fail-fast saat secret masih default di `APP_ENV=production` |
| Camera selector | `test_device_selector.py` | Pilih kamera by-serial (enum GigE tidak deterministik) |
| Streaming | `test_streaming_service.py` | MJPEG keep-alive multi-viewer |
| SDK boundary | `test_hikrobot_frame.py`, `test_mvs_error.py` | Konversi frame + mapping error SDK |
| **License** | `test_license_manager.py`, `test_license_local_repo.py` | Verifikasi JWS **Ed25519 asli** (tamper/kid/foreign-key ditolak), state machine efektif (ACTIVE/TRIAL/EXPIRED/CANCEL/GRACE, online↔offline, anti-rollback `server_time`, device-id, `nbf`), warning window, dan hash-chain + high-water-mark di SQLite |

**Prinsip menambah test:**
- Uji **logic murni** (domain, state machine, persistence SQLite) — hindari test yang menyeret framework berat/hardware ke CI.
- Untuk async, ikuti pola `asyncio.run` (lihat `test_event_broadcast_worker.py` / `test_license_local_repo.py`).
- Kalau menambah modul baru ke lint, perluas juga scope `ruff check` di `ci.yml` (bertahap per modul yang sudah bersih).

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `8000` | Internal container port |
| `FRONTEND_URL` | `http://localhost:3050` | CORS allowed origin |
| `BACKEND_URL` | `http://localhost:2500` | palmgrade-api base URL |
| `BACKEND_API_VER` | `/api/v1` | Prefix versi API untuk canonical events URL |
| `WEBHOOK_SECRET` | — | Shared secret header value — must match palmgrade-api |
| `ENABLE_WEBHOOK` | `true` | Toggle webhook posting |
| `MODEL_FILE` | `best_3class_v2.pt` | YOLO model filename in `models/release/` |
| `CONF_THRESHOLD` | `0.75` | YOLO confidence threshold |
| `MINIMUM_SIZE` | `460000` | Min bounding box area in px² |
| `CAMERA_TYPE` | `hikrobot` | `hikrobot` / `opencv` / `photo` |
| `CAMERA_DEVICE_INDEX` | `0` | Camera index (0/1/2 per line) |
| `CAMERA_VIDEO_PATH` | — | Path video file di dalam container (kalau `CAMERA_TYPE=opencv` + video) |
| `CAMERA_PHOTO_PATH` | — | Path gambar test (kalau `CAMERA_TYPE=photo`) |
| `CAMERA_WIDTH` | `320` | Frame width (OpenCV only; docker-compose Hikrobot: `2448`) |
| `CAMERA_HEIGHT` | `240` | Frame height (OpenCV only; docker-compose Hikrobot: `2048`) |
| `CAMERA_FPS` | `30` | Frame rate (docker-compose menetapkan `25`) |
| `YOLO_SKIP_FRAMES` | `1` | Jalankan YOLO setiap N frame (`1` = tiap frame; `>1` hemat CPU saat tes video) |
| `STREAM_WIDTH` | `1280` | MJPEG stream width (resize before encode) |
| `STREAM_HEIGHT` | `720` | MJPEG stream height (resize before encode) |
| `STREAM_FPS` | `12` | FPS MJPEG stream — decoupled dari `CAMERA_FPS` |
| `ROI_X1` | `0` | Left edge of detection ROI box — **koordinat dalam stream resolution** (`STREAM_WIDTH × STREAM_HEIGHT`, default 1280×720) |
| `ROI_Y1` | `0` | Top edge of detection ROI box |
| `ROI_X2` | `0` | Right edge — `0` = full stream width. Wajib > `ROI_X1` |
| `ROI_Y2` | `0` | Bottom edge — `0` = full stream height. Wajib > `ROI_Y1` |
| `MACHINE_ID` | — | UUID from `machines` table — set per line |
| `LINE_1_MACHINE_ID` | — | Used by docker-compose for line 1 |
| `LINE_2_MACHINE_ID` | — | Used by docker-compose for line 2 |
| `LINE_3_MACHINE_ID` | — | Used by docker-compose for line 3 |
| `LIC_ENABLED` | `false` | Enable license guard middleware |
| `UPLOAD_HOUR` | `0` | Daily upload cron — hour (0–23) |
| `UPLOAD_MINUTE` | `0` | Daily upload cron — minute (0–59) |
| `DESTINATION_UPLOAD` | — | Upload destination path |
| `DEBUG_MODEL_OUTPUT` | `false` | Log raw YOLO output untuk debugging (`core/logging.py`) |

---

## Git Workflow

- **Default branch**: `staging` — all development goes here first
- **Branch protection**: org ruleset blocks direct push to `main` and `staging` — use PR
- **Flow**: create branch from `staging` → PR → squash merge to `staging` → PR → squash merge to `main`
