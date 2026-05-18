# CLAUDE.md — palmgrade-vision (ripe-recognition-main)

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

1 model (`3_class.pt`) mendeteksi 3 kelas sekaligus: `acc`, `rej`, `tp`.

Flow deteksi (single-trigger, bukan vote):
- `TP` yang terlihat → simpan di `_last_tp` sementara
- `ACC`/`REJ` yang masuk zona deteksi → save buah (JPEG + `_ripeness.json`)
- Kalau ada `_last_tp` → save juga `_tp.json` (tanpa gambar) dengan timestamp yang sama
- `MINIMUM_SIZE` = 460000 px² — kalau area buah < threshold → auto jadi `rej`

Save format:
- `{timestamp}_auto.jpg` — gambar buah
- `{timestamp}_auto_ripeness.json` — metadata buah
- `{timestamp}_auto_tp.json` — metadata TP (tanpa gambar, dipair dengan buah)
- `list_today_results()` di `ResultRepository` merge keduanya per base_name

Response schema (bukan `status`/`confidence` lagi):
```json
{
  "ripeness_status": "acc" | "rej",
  "ripeness_confidence": 0.92,
  "tp_status": "TP" | null,
  "tp_confidence": 0.88
}
```

---

## Critical Invariants — Jangan Diubah Tanpa Diskusi

### 1. `_processed_objects` di `FrameProcessingWorker`

Set internal di worker. Setelah track_id di-save, masukkan ke `_processed_objects`.
Di iterasi berikutnya, `if track_id in _processed_objects: continue`.

Tanpa ini, buah yang sama bisa tersimpan berkali-kali.

### 2. `state.lock` wajib saat akses kamera

`FrameCaptureWorker.run_once()` dan `CaptureService.capture_manual_reject()`
keduanya akses kamera fisik. Keduanya wajib acquire `state.lock` dulu.

Tanpa ini, concurrent access ke Hikrobot SDK bisa crash.

### 3. Drop-old-frame policy di `result_queue`

Saat `result_queue` penuh, buang frame lama dulu (non-blocking get),
baru masukkan frame baru. Jangan pakai blocking `put()`.

Tanpa ini, MJPEG stream hang saat processing lebih lambat dari capture.

### 4. `get_capture_service()` tidak boleh `@lru_cache`

Camera diinject via `set_camera()` di startup event, bukan saat import.
Kalau di-cache, nilai `_camera = None` akan difreeze sebelum startup.

### 5. `repo_root` pakai `parents[4]`

File `config.py` ada di `src/ripe_recognition/core/config.py`.
Untuk naik ke project root butuh 4 level: `core → ripe_recognition → src → ripe-recognition-main`.

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

- Production: `HikrobotCamera` (butuh Hikrobot SDK + hardware)
- Development: `OpenCVCamera` (`cv2.VideoCapture`, webcam atau video file)
- Ganti di `main.py` startup event saat development lokal

---

## What To Do Before Touching a File

1. Baca `docs/target-architecture.md` untuk boundary rules
2. Cek `docs/backend-overview.md` untuk API contracts dan flow
3. Pastikan perubahan tidak melanggar layer constraints di atas
4. Kalau mau tambah env var baru, tambah di `core/config.py` dengan default yang masuk akal

---

## Reference Docs

- `docs/target-architecture.md` — keputusan desain final (jangan ubah tanpa diskusi)
- `docs/migration-progress.md` — progress dan next steps
- `docs/backend-overview.md` — endpoint, flow, env var
- `docs/frontend-overview.md` — API contract yang diharapkan FE
- `docs/refactor-checklist.md` — checklist per layer
