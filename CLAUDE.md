# CLAUDE.md — palmgrade-vision

Agent instructions for Claude Code, Codex, Copilot, and similar AI tools.

---

## System Role

`palmgrade-vision` is the Python AI camera service for the Palmgrade palm oil grading platform.
It runs as **3 separate Docker containers** (one per camera line), each on its own port.
It is one of **three repos** that make up the full system:

| Repo | Role | Tech |
|---|---|---|
| **`palmgrade-vision`** | **AI camera + inference (per line)** | **Python / FastAPI** |
| `palmgrade-api` | Business logic, auth, SSE broker | Node.js / Express |
| `palmgrade-frontend` | Operator dashboard UI | Next.js 15 |

For the full system architecture, see `../ARCHITECTURE.md`.

---

## Architecture: Flat Layered Structure

Setiap layer punya boundary yang ketat. Jangan campur responsibility antar layer.

```
route -> controller -> service -> repository / pipeline / integration
```

| Layer | Folder | Tanggung jawab |
|---|---|---|
| Routes | `routes/` | Deklarasi endpoint dan Depends() saja |
| Controllers | `controllers/` | Terima request, panggil service, return response |
| Services | `services/` | Orchestrate business flow |
| Repositories | `repositories/` | Baca/tulis file (JSON, JPEG) |
| Pipelines | `pipelines/` | YOLO inference + frame processing |
| Integrations | `integrations/` | External: camera SDK, webhook, storage, scheduler |
| Workers | `workers/` | Background loop + shared runtime state |
| Domain | `domain/` | Business rule murni (voting, status, entities) |
| Schemas | `schemas/` | Pydantic request/response models |
| Core | `core/` | Config, logging, constants, DI wiring |

---

## Layer Constraints (strict)

**Routes:**
- Boleh: deklarasi path, method, Depends(), return type hint
- Dilarang: logic apapun, akses file, akses model, akses queue

**Controllers:**
- Boleh: terima request, panggil satu service, handle HTTP error (HTTPException)
- Dilarang: akses repository langsung, akses queue, panggil YOLO

**Services:**
- Boleh: gabungkan repository + pipeline + integration, jalankan business flow
- Dilarang: SQL, detail SDK vendor, akses file langsung

**Repositories:**
- Boleh: baca/tulis file JSON dan JPEG via `LocalFileStorage`
- Dilarang: rule PASS/FAIL, logic HTTP, logic model inference, logic voting

**Pipelines:**
- Boleh: YOLO inference, frame processing, draw bounding box
- Dilarang: HTTP call, file save, business rules, akses queue

**Domain:**
- Boleh: pure function, pure dataclass, tidak ada I/O sama sekali
- Dilarang: import `cv2`, import `httpx`, import `fastapi`, baca/tulis file

**Workers:**
- Boleh: loop background, akses queue, hold lock, akses RuntimeState
- Dilarang: langsung return HTTP response, langsung simpan ke file (delegasikan ke repo)

---

## Detection Logic

1 model (`best_3class_v2.pt`) mendeteksi 3 kelas sekaligus: `acc`, `rej`, `tp`.

Flow deteksi (single-trigger, bukan vote):
- `TP` yang terlihat → simpan di `_last_tp` sementara
- `ACC`/`REJ` yang masuk zona deteksi → save buah (JPEG + `_ripeness.json`)
- Kalau ada `_last_tp` → save juga `_tp.json` (tanpa gambar) dengan timestamp yang sama
- `MINIMUM_SIZE` = 460000 px² — kalau area buah < threshold → auto jadi `rej`

**Detection zone — ROI Box:**

Zona deteksi dikontrol via 4 env var:
- `ROI_X1`, `ROI_Y1` — sudut kiri atas kotak ROI (px)
- `ROI_X2`, `ROI_Y2` — sudut kanan bawah kotak ROI (px)

**PENTING: koordinat ROI dalam stream resolution space** (`STREAM_WIDTH × STREAM_HEIGHT`, default 1280×720) — bukan resolusi sensor kamera.
`draw_roi()` dipanggil di `DisplayWorker` **setelah** frame di-resize ke stream resolution, sehingga operator bisa kalibrasi langsung dari apa yang mereka lihat di browser.

Logic: pusat bounding box `(cx, cy) = ((x1+x2)/2, (y1+y2)/2)` harus berada di dalam ROI.
Default `0,0,0,0` = full frame (ROI_X2=0 → lebar stream, ROI_Y2=0 → tinggi stream).
Wajib: `ROI_X2 > ROI_X1` dan `ROI_Y2 > ROI_Y1` — jika tidak, ROI tidak digambar dan tidak ada zona deteksi.
TP tidak dicek ROI — selalu diterima dari posisi manapun.

ROI ditampilkan sebagai overlay kuning semi-transparan (25% opacity) + border di MJPEG stream via `draw_roi()` di `DisplayWorker`.
Kalibrasi: set `ROI_X1/Y1/X2/Y2` di `.env` sesuai area conveyor (dalam koordinat 1280×720), lalu `make start`.

Save format:
- `{timestamp}_auto.jpg` — gambar buah
- `{timestamp}_auto_ripeness.json` — metadata buah
- `{timestamp}_auto_tp.json` — metadata TP (tanpa gambar, dipair dengan buah)
- `list_today_results()` di `ResultRepository` merge keduanya per base_name

**Outbox pattern — JANGAN kirim event langsung ke API**

Semua event (auto detection + manual reject) ditulis ke `OutboxStore` (SQLite) terlebih dahulu.
`OutboxRetryWorker` yang deliver ke API secara async dengan retry + exponential backoff.

```
FrameProcessingWorker / CaptureService
    → OutboxStore.add_event(event_id, machine_id, payload)   ← tulis ke SQLite dulu
        → OutboxRetryWorker (daemon thread, poll setiap 10s)
            → POST {canonical_events_url} with x-webhook-secret header
                → palmgrade-api /api/v1/internal/vision/events
```

`canonical_events_url` = `{backend_url}{backend_api_ver}/internal/vision/events` (dari `Settings.canonical_events_url`)

**Event payload yang ditulis ke outbox** — field names harus PERSIS:
```json
{
  "event_id": "uuid-v4-generated",
  "machine_id": "uuid",
  "assignment_id": "uuid-or-null",
  "truck_id": "uuid",
  "timestamp": "ISO string",
  "image_path": "captures/results/{date}/{ts}_auto.jpg",
  "prediction": "Acc" | "Rej",
  "ripeness_status": "ACC" | "REJ",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS" | null,
  "tp_confidence": 0.88,
  "capture_type": "auto" | "manual",
  "bounding_box": { "x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100 }
}
```

**Aturan event:**
- `ripeness_status` harus UPPERCASE (`"ACC"`/`"REJ"`) — API DTO validasi case-sensitive
- `prediction` wajib ada (`"Acc"` atau `"Rej"`) — API DTO field required
- `tp_status` harus `"PASS"` (bukan `"TP"`) atau `null`
- Event selalu ditulis ke outbox, termasuk capture reject tanpa truck (`truck_id` boleh `None`)
- `event_id` adalah UUID baru per event — dipakai API untuk idempotency
- `assignment_id` diambil dari `state.current_assignment_id` (diset saat `/internal/assignment` dipanggil)

**Internal endpoints — menerima command dari palmgrade-api:**
- `POST /internal/assignment` — set `state.current_truck_id` + `state.current_assignment_id`; protected by `x-internal-secret: WEBHOOK_SECRET`
- `POST /internal/manual-reject` — trigger `capture_manual_reject()` via `run_in_executor`; protected by same header

**`WEBHOOK_SECRET` punya dual purpose:**
- Outbox delivery ke API: dikirim sebagai `x-webhook-secret` header
- API command ke vision: diterima sebagai `x-internal-secret` header (nilai sama)

**`_last_tp` dict menyimpan `"tp_status": "PASS"` (bukan `"TP"` lagi)**

---

## Critical Invariants — Jangan Diubah Tanpa Diskusi

### 0. OutboxStore harus ditulis SEBELUM event dianggap tersimpan

`FrameProcessingWorker` dan `CaptureService` WAJIB memanggil `self.outbox_store.add_event(...)` sebelum fungsi kembali.
**Jangan pernah mengirim event langsung ke API** (direct httpx/webhook call) dari worker thread — gunakan outbox.

`OutboxStore.add_event()` di-wrap dalam `try/except` dengan `logger.error` — bukan `try/except: pass`.
Kalau SQLite penuh atau disk full, log error tapi jangan crash detection loop.

Ini penting karena: kalau API down atau network putus, event tidak hilang — OutboxRetryWorker akan retry.

### 1. `_processed_objects` di `FrameProcessingWorker`

Set internal di worker. Setelah track_id di-save, masukkan ke `_processed_objects`.
Di iterasi berikutnya, `if track_id in _processed_objects: continue`.

**Jangan pernah panggil `_processed_objects.discard(tid)`** — buah yang sama akan tersimpan ulang di siklus berikutnya.

Tanpa ini, buah yang sama bisa tersimpan berkali-kali.

### 2. `state.lock` wajib saat akses kamera

`FrameCaptureWorker.run_once()` dan `CaptureService.capture_manual_reject()`
keduanya akses kamera fisik. Keduanya wajib acquire `state.lock` dulu.

Tanpa ini, concurrent access ke Hikrobot SDK bisa crash.

### 3. MJPEG broadcast via `threading.Condition`, bukan `result_queue`

`FrameProcessingWorker` menulis ke `state.latest_frame` dan memanggil `state.frame_condition.notify_all()`.
`StreamingService.generate_frames()` di setiap viewer menunggu dengan `frame_condition.wait(timeout=0.5)`.

Jangan ganti kembali ke `Queue.get()` — pattern lama hanya melayani satu viewer, yang lain tidak dapat frame.
`event_queue` (untuk SSE/webhook) tetap pakai drop-old: `get_nowait()` + `put_nowait()`.

### 4a. `get_outbox_store()` BOLEH `@lru_cache` — SQLite adalah singleton

`OutboxStore` aman di-cache karena menggunakan `threading.Lock` dan membuka fresh `sqlite3.Connection` per operasi.
`@lru_cache` pada `get_outbox_store()` memastikan satu DB path dipakai oleh semua caller (worker, service, health).

### 4. `get_capture_service()` tidak boleh `@lru_cache`

Camera diinject via `set_camera()` di startup event, bukan saat import.
Kalau di-cache, nilai `_camera = None` akan difreeze sebelum startup.

### 5. `repo_root` pakai `parents[3]`

File `config.py` ada di `src/palmgrade/core/config.py`.
Untuk naik ke project root butuh 3 level: `core → palmgrade → src → palmgrade-vision`.
Di Docker, path adalah `/app/src/palmgrade/core/config.py` → `parents[3]` = `/app` ✅

### 6. Startup/shutdown pakai `lifespan`, bukan `@app.on_event`

`@app.on_event("startup/shutdown")` sudah deprecated sejak FastAPI 0.93.
Gunakan `@asynccontextmanager async def lifespan(app)` yang di-pass ke `FastAPI(lifespan=lifespan)`.

Upload scheduler dan camera disconnect dikelola sebagai variabel lokal di dalam `lifespan` — tidak perlu global.

### 7. MJPEG ditulis HANYA oleh `DisplayWorker`

Ada 3 worker thread dengan tanggung jawab eksklusif:
- `FrameCaptureWorker` — grab frame dari kamera, set `state.latest_raw_frame`, push ke `frame_queue`
- `DisplayWorker` — baca `last_yolo_frame` + `last_yolo_results` (paired), draw ROI + box + zone lines, encode JPEG, tulis `state.latest_frame`; **berjalan di `settings.stream_fps` (default 12)** — decoupled dari camera FPS
- `FrameProcessingWorker` — YOLO inference dari `frame_queue`, set `state.last_yolo_frame` + `state.last_yolo_results` (paired), detection/save/outbox logic

**`STREAM_FPS` memisahkan FPS MJPEG dari FPS kamera/inferensi.** Kamera+YOLO tetap jalan di `CAMERA_FPS` (default 24), tapi browser operator hanya decode stream di `STREAM_FPS` (default 12). `DisplayWorker` dibuat dengan `target_fps=settings.stream_fps or 12` di `main.py`.

**Jangan tambahkan penulisan `state.latest_frame` di worker mana pun selain `DisplayWorker`.**
Dua writer ke `state.latest_frame` menyebabkan glitch/flicker di MJPEG stream.

### 12. `DisplayWorker` harus pakai `last_yolo_frame`, bukan `latest_raw_frame`

`last_yolo_frame` adalah frame yang BENAR-BENAR di-proses YOLO, always paired dengan `last_yolo_results`.
`FrameProcessingWorker` set keduanya secara berurutan setelah satu YOLO run.

**Jangan render `last_yolo_results` di atas `latest_raw_frame`** — pada CPU, inference bisa 500ms-2000ms. Dalam waktu itu conveyor bergerak dan buah sudah pindah posisi. Box akan muncul di tempat yang salah.

Kalau `last_yolo_frame` belum tersedia (sebelum YOLO pertama run), fallback ke `latest_raw_frame`.

Draw order di `DisplayWorker.run_once()`:
1. `draw_boxes()` — bounding boxes di atas frame (sebelum resize)
2. `cv2.resize()` — upscale ke stream resolution (STREAM_WIDTH × STREAM_HEIGHT)
3. `draw_roi()` — ROI highlight (overlay kuning semi-transparan + border) **setelah resize**

`draw_roi()` dipanggil **setelah** resize karena koordinat ROI harus dalam stream space, bukan sensor space.
Ini memungkinkan operator mengkalibrasi ROI langsung dari apa yang terlihat di browser (1280×720).

### 8. Manual capture JSON pakai suffix `_ripeness`

File JSON dari manual capture harus dinamai `{timestamp}_manual_ripeness.json`, bukan `{timestamp}_manual.json`.

`ResultRepository.list_today_results()` membaca suffix `_ripeness` untuk extract `ripeness_status` dan `image_url`.
Tanpa suffix ini, manual capture jatuh ke branch `else` (format lama) yang tidak selalu kompatibel.

### 9. Worker threads wajib punya exception handling di `run_loop`

Semua tiga worker (`FrameCaptureWorker`, `DisplayWorker`, `FrameProcessingWorker`) punya `run_loop` yang membungkus `run_once()` dengan `try/except Exception`:

```python
def run_loop(self) -> None:
    while True:
        try:
            self.run_once()
        except Exception:
            logger.exception("Unhandled error in XxxWorker.run_once")
            time.sleep(1)
```

**Jangan hapus try/except ini** — tanpanya thread mati diam-diam, watchdog restart tapi log tidak ada stack trace.

### 10. `FrameCaptureWorker` harus punya `device_index`

Constructor `FrameCaptureWorker` menerima `device_index: int` dan menyimpannya sebagai `self._device_index`.
Saat reconnect, `_try_reconnect()` memanggil `self.camera.connect(index=self._device_index)`.

**Jangan pernah panggil `self.camera.connect()` tanpa `index=`** — default `index=0` akan membuat line-2 dan line-3 reconnect ke kamera yang salah.

### 11. `get_health_service()` tidak boleh `@lru_cache`

Sama seperti `get_capture_service()`, `get_health_service()` memanggil `get_camera()` yang raise `RuntimeError` sebelum startup.
Jika di-cache, nilai `_camera = None` akan difreeze sebelum lifespan berjalan.

---

## Dependency Injection

Semua dependency di-wire di `core/dependencies.py`.

- Gunakan `@lru_cache` untuk singleton (Settings, ModelRegistry, Services, dsb.)
- Inject lewat `Depends()` di route parameter
- Jangan buat instance langsung di controller atau service
- Exception: `get_capture_service()` — tidak di-cache karena butuh camera yang diset saat startup

---

## Naming Conventions

- File: `snake_case.py`
- Class: `PascalCase`
- Function/variable: `snake_case`
- Constant: `UPPER_SNAKE_CASE` (di `core/constants.py`)
- Env var: `UPPER_SNAKE_CASE` (di `.env`)

---

## File & Path Rules

- Semua path di-manage lewat `Settings` (di `core/config.py`)
- Jangan hardcode path di service atau repository
- Format `image_url`: `captures/results/{date}/{timestamp}_auto.jpg`
  — harus konsisten dengan StaticFiles mount `/captures` → `artifacts/`
- Folder artifacts dibuat otomatis di startup event

---

## Camera: Development vs Production

Dikontrol lewat env var `CAMERA_TYPE` (default: `hikrobot`):

| `CAMERA_TYPE` | Class | Kapan dipakai |
|---|---|---|
| `hikrobot` | `HikrobotCamera` | Production — butuh Hikrobot SDK + hardware |
| `opencv` | `OpenCVCamera` | Development — webcam (`CAMERA_DEVICE_INDEX`) atau video file |
| `photo` | `PhotoCamera` | Testing — image tunggal (`CAMERA_PHOTO_PATH`) |

Tidak perlu edit `main.py` lagi saat switch environment — cukup set env var.

---

## Docker-Only Development Setup

palmgrade-vision **tidak punya `.venv` host** — semua dijalankan via Docker.

```
docker-compose.yml volumes:
  - .:/app                      # source code dari host (hot-reload di dev)
  - /app/.venv                  # anonymous volume — shadow host .venv, pakai packages dari image
  - ./artifacts/line-N:/app/artifacts
  - ./models:/app/models:ro
```

`entrypoint.sh` ada di `/entrypoint.sh` (luar `/app`) — bukan `/app/entrypoint.sh`.
Kalau di dalam `/app`, akan tertimpa oleh volume mount `.:/app`.

`load_dotenv(override=False)` wajib di `main.py` — host `.env` ikut masuk container via bind mount.
`docker-compose.yml` environment section **selalu menang** atas host `.env`.

**Shared image pattern:**
`ripe-line-1` punya `build:` + `image: palmgrade-vision:latest` di docker-compose.
`ripe-line-2` dan `ripe-line-3` hanya punya `image: palmgrade-vision:latest` (tanpa `build:`).
Artinya: build image cukup sekali, 3 container share image yang sama — hemat disk ~20GB.
Jangan kembalikan `build:` ke line-2/3 kecuali ada alasan khusus.

**`network_mode: host` — wajib untuk kamera GigE Vision:**
Kamera Hikrobot terhubung via RJ45 LAN (GigE Vision protocol). SDK menggunakan UDP broadcast untuk `MV_CC_EnumDevices()`.
Docker bridge network memblok UDP broadcast ini — container tidak bisa menemukan kamera.
Solusinya: `network_mode: host` di setiap service — container langsung pakai network stack host.
Konsekuensi: `ports:` dan `extra_hosts:` tidak berlaku (diabaikan). Setiap container harus bind ke port yang berbeda via `APP_PORT` env var (8001/8002/8003).

**GPU passthrough — wajib untuk YOLO inference:**
Tanpa GPU config, Docker tidak expose GPU ke container — YOLO jalan di CPU, inference 10x lebih lambat.
Tambahkan ke setiap service di docker-compose:
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```
Membutuhkan NVIDIA Container Toolkit di host. `apt install nvidia-container-toolkit` **tidak cukup** — harus tambah repo NVIDIA dulu:
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit && sudo systemctl restart docker
```

**Production deployment checklist (pindah ke PC baru) — urutan ini penting:**
1. Install NVIDIA Container Toolkit (perintah di atas) → `docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi` untuk verifikasi
2. Install Hikrobot MVS SDK di host (`/opt/MVS/`)
3. Copy model: `mkdir -p models/release` + copy `best_3class_v2.pt`
4. Configure `.env`: `LINE_1/2/3_MACHINE_ID`, `BACKEND_URL`, `WEBHOOK_SECRET`, `CAMERA_TYPE=hikrobot`, `CAMERA_FPS=25`
5. `make up` — otomatis copy SDK dari `/opt/MVS/` ke `sdk/`, build GPU image, start semua line
6. Verifikasi: `curl http://localhost:8001/health/detail | grep gpu_available`

**Make commands:**
```
make up         # production: copy SDK, build GPU+SDK, start semua line
make up-dev     # development: build CPU tanpa SDK, start semua line
make start      # start semua line tanpa rebuild (pakai image yang sudah ada)
make up-1       # start line-1 saja tanpa rebuild
make up-2       # start line-2 saja tanpa rebuild
make up-3       # start line-3 saja tanpa rebuild
make logs-1     # tail logs line-1
make logs       # tail logs semua line (combined)
make down       # stop semua
make ps         # status semua container
make rebuild    # rebuild image GPU/CUDA (tanpa SDK) — selalu GPU, tidak ada CPU variant
make rebuild-gpu # alias make rebuild (sama persis)
make clean      # down + hapus local image
```

**`requirements.txt`** — jangan pernah replace dengan output `pip freeze` dari environment lain.
Hanya include packages yang benar-benar diimport di source code:
`fastapi`, `uvicorn[standard]`, `python-multipart`, `python-dotenv`, `ultralytics`, `torch`, `torchvision`, `numpy`, `opencv-python`, `httpx`, `pydantic`, `apscheduler`, `aiosqlite`, `cryptography`, `psutil`.

---

## What To Do Before Touching a File

1. Baca `docs/target-architecture.md` untuk boundary rules
2. Cek `docs/backend-overview.md` untuk API contracts dan flow
3. Pastikan perubahan tidak melanggar layer constraints di atas
4. Kalau mau tambah env var baru, tambah di `core/config.py` dengan default yang masuk akal

---

## Git Workflow

- **Default branch**: `staging` — semua development di sini
- **Branch protection**: org ruleset blocks direct push ke `main` dan `staging` — wajib lewat PR
- **Flow**: buat branch dari `staging` → PR → squash merge ke `staging` → PR → squash merge ke `main`
- **Commit messages**: jangan pernah include "Co-Authored-By: Claude" atau referensi AI apapun

---

## Reference Docs

- `docs/architecture.md` — desain arsitektur final (jangan ubah tanpa diskusi)
- `docs/backend-overview.md` — endpoint, flow, env var
