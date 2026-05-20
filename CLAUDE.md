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

**Detection zone — direction-aware:**

Zona deteksi dikontrol via 3 env var:
- `CONVEYOR_DIRECTION` = `rtl` | `ltr` | `ttb` | `btt` — arah gerak conveyor
- `DETECTION_ENTRY_OFFSET` = jarak (px) dari sisi masuk ke garis deteksi (biru)
- `DETECTION_EXIT_OFFSET` = jarak (px) dari sisi keluar ke garis exit (hijau)

Logic per direction:

| Direction | Leading coord | Entry condition | Exit condition |
|---|---|---|---|
| `rtl` | `x1` | `x1 ≤ width − entry_offset` | `x1 < exit_offset + margin` |
| `ltr` | `x2` | `x2 ≥ entry_offset` | `x2 > width − exit_offset − margin` |
| `ttb` | `y1` | `y1 ≥ entry_offset` | `y1 > height − exit_offset − margin` |
| `btt` | `y2` | `y2 ≤ height − entry_offset` | `y2 < exit_offset + margin` |

TP diizinkan dari manapun (tidak dicek entry boundary).
Nilai wajib dikalibrasi di lapangan per kamera dan per line.

Save format:
- `{timestamp}_auto.jpg` — gambar buah
- `{timestamp}_auto_ripeness.json` — metadata buah
- `{timestamp}_auto_tp.json` — metadata TP (tanpa gambar, dipair dengan buah)
- `list_today_results()` di `ResultRepository` merge keduanya per base_name

**Webhook payload ke palmgrade-api** — field names dan values harus PERSIS seperti ini:
```json
{
  "timestamp": "ISO string",
  "image_path": "captures/results/{date}/{ts}_auto.jpg",
  "prediction": "Acc" | "Rej",
  "ripeness_status": "ACC" | "REJ",
  "ripeness_confidence": 0.92,
  "tp_status": "PASS" | null,
  "tp_confidence": 0.88,
  "capture_type": "auto" | "manual",
  "truck_id": "uuid",
  "machine_id": "uuid",
  "bounding_box": { "x_min": 0, "y_min": 0, "x_max": 100, "y_max": 100 }
}
```

**Aturan webhook:**
- `ripeness_status` harus UPPERCASE (`"ACC"`/`"REJ"`) — API DTO validasi case-sensitive
- `prediction` wajib ada (`"Acc"` atau `"Rej"`) — API DTO field required
- `tp_status` harus `"PASS"` (bukan `"TP"`) atau `null` — API DTO hanya accept `"PASS"/"FAIL"/"UNKNOWN"`
- Webhook hanya dikirim kalau `truck_id` tidak `None` — tanpa truck, API DTO reject dengan 400
- `_last_tp` dict menyimpan `"tp_status": "PASS"` (bukan `"TP"` lagi)

---

## Critical Invariants — Jangan Diubah Tanpa Diskusi

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
- `DisplayWorker` — baca `last_yolo_frame` + `last_yolo_results` (paired), draw ROI + box + zone lines, encode JPEG, tulis `state.latest_frame`
- `FrameProcessingWorker` — YOLO inference dari `frame_queue`, set `state.last_yolo_frame` + `state.last_yolo_results` (paired), detection/save/webhook logic

**Jangan tambahkan penulisan `state.latest_frame` di worker mana pun selain `DisplayWorker`.**
Dua writer ke `state.latest_frame` menyebabkan glitch/flicker di MJPEG stream.

### 12. `DisplayWorker` harus pakai `last_yolo_frame`, bukan `latest_raw_frame`

`last_yolo_frame` adalah frame yang BENAR-BENAR di-proses YOLO, always paired dengan `last_yolo_results`.
`FrameProcessingWorker` set keduanya secara berurutan setelah satu YOLO run.

**Jangan render `last_yolo_results` di atas `latest_raw_frame`** — pada CPU, inference bisa 500ms-2000ms. Dalam waktu itu conveyor bergerak dan buah sudah pindah posisi. Box akan muncul di tempat yang salah.

Kalau `last_yolo_frame` belum tersedia (sebelum YOLO pertama run), fallback ke `latest_raw_frame`.

Draw order di `DisplayWorker.run_once()`:
1. `draw_roi()` — ROI highlight (overlay semi-transparan, background)
2. `draw_boxes()` — bounding boxes di atas ROI
3. `_draw_zone_lines()` — entry/exit lines paling atas

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
Membutuhkan NVIDIA Container Toolkit di host: `apt install nvidia-container-toolkit`.

**Make commands:**
```
make up         # build + up semua line (build hanya satu kali via line-1)
make up-1       # build image + up line-1
make up-2       # up line-2 (reuse image yang sudah ada)
make up-3       # up line-3 (reuse image yang sudah ada)
make logs-1     # tail logs line-1
make logs       # tail logs semua line (combined)
make down       # stop semua
make ps         # status semua container
make rebuild    # rebuild image
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
