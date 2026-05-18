# Migration Progress

## Purpose

Dokumen ini dipakai untuk mencatat progress pekerjaan migrasi dari
`sawit-main` ke `ripe-recognition-main`.

Dokumen ini berbeda dari `target-architecture.md`.

- `target-architecture.md` = keputusan desain final
- `migration-progress.md` = catatan eksekusi pekerjaan dan next step

## Current Status

- Status: `in progress`
- Last updated: `2026-05-18`
- Current phase: `phase 1 complete (code) — awaiting hardware verification`

## Completed Work

### 2026-05-17

1. Explore codebase `sawit-main` dan `ripe-recognition-main`.
2. Identifikasi masalah utama:
   - logic masih menumpuk di `predict.py`
   - API, camera, inference, scheduler, webhook, dan persistence belum terpisah
   - dependency dan config masih bercampur
3. Finalisasi keputusan arsitektur baru.
4. Tulis dokumen acuan di `docs/target-architecture.md`.
5. Buat skeleton project baru berbasis `src/ripe_recognition/`.
6. Buat layer berikut:
   - `routes/`
   - `controllers/`
   - `services/`
   - `repositories/`
   - `pipelines/`
   - `integrations/`
   - `workers/`
   - `domain/`
   - `schemas/`
   - `core/`
7. Tambahkan wiring FastAPI dasar di `src/ripe_recognition/main.py`.
8. Tambahkan CLI skeleton di folder `cli/`.
9. Tambahkan folder `artifacts/`, `tests/`, dan `models/release|experiments`.
10. Verifikasi syntax dasar dengan compile check.

## Current Project State

Yang sudah ada sekarang:

- dokumen arsitektur final
- skeleton folder dan file dasar
- placeholder service/repository/integration
- dependency wiring dasar
- endpoint skeleton untuk:
  - health
  - inspection
  - streaming
  - capture
  - truck

Yang belum dipindahkan:

- logic asli dari `sawit-main/predict.py`
- camera SDK implementation aktual
- realtime worker flow aktual
- webhook flow aktual
- scheduler aktual
- pipeline YOLO aktual

## Migration Strategy

### Dua Fase Besar

**Fase 1 — Make it Work**

Tujuan: semua endpoint dan realtime flow berjalan persis seperti `sawit-main`,
hanya strukturnya yang sudah rapi sesuai target-architecture.

Selesai jika:
- server bisa distart dari `ripe-recognition-main`
- `/api/video_feed` stream berjalan
- `/api/results_today` mengembalikan data yang benar
- `/api/set_truck`, `/api/capture_reject` berfungsi
- WebSocket `/ws/results` push event ke client
- scheduler upload berjalan di waktu yang dikonfigurasi
- `predict.py` lama sudah bisa dinonaktifkan

**Fase 2 — Make it Clean** (setelah Fase 1 selesai dan stabil)

Tujuan: rapikan hal-hal yang tidak sempat dibenerin di Fase 1.

Contoh:
- tambah unit test untuk voting dan status rule
- evaluasi apakah `uploader.py` perlu diganti implementasi yang lebih robust
- pisahkan dependency runtime dan development di `requirements.txt`
- tambah integration test untuk endpoint utama

---

## Next Steps (Fase 1)

Urutan pengerjaan yang disarankan, dari foundation ke atas:

1. **`core/config.py`** — tambahkan semua env var yang masih kurang:
   `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS`, `MODEL_SIZE`, `MODEL_VERSION`,
   `CLS_MODEL_SIZE`, `CLS_MODEL_VERSION`, `CONF_THRESHOLD`, `VOTE_THRESHOLD`,
   `BORDER_THICKNESS`, `FONT_SCALE`, `FONT_THICKNESS`, `ROI_SCALE`,
   `BACKEND_URL`, `BACKEND_API_VER`, `WEBHOOK_SECRET`,
   `UPLOAD_HOUR`, `UPLOAD_MINUTE`, `DESTINATION_UPLOAD`.

2. **`integrations/camera/hikrobot_camera.py`** — migrate actual SDK code dari
   `sawit-main/helpers/hikrobot_camera.py`. Jangan ubah logikanya.

3. **`integrations/notifications/webhook_client.py`** — migrate actual `httpx`
   call dari `sawit-main/helpers/webhook.py`.

4. **`integrations/scheduler/upload_scheduler.py`** — migrate APScheduler setup
   dari `sawit-main/helpers/scheduler.py` dan uploader dari `helpers/uploader.py`.

5. **`integrations/storage/local_file_storage.py`** — tambahkan method
   `write_image()` untuk `cv2.imwrite`. Sekarang hanya ada `write_json`.

6. **`workers/runtime_state.py`** — tambahkan field yang masih kurang:
   `track_history`, `classified_labels`, `lock`, dan `websocket_clients`.

7. **`domain/voting.py`** — tambahkan field `processed: bool` ke `VoteTracker`
   untuk mencegah duplicate result saat satu buah sudah melewati vote threshold.

8. **`pipelines/realtime_inspection_pipeline.py`** — migrate logic
   `detect_and_classify()` dari `predict.py`. Ini bagian terbesar.
   Termasuk: YOLO tracking, voting, draw_boxes, save_result, event_queue, webhook.

9. **`workers/frame_capture_worker.py`** — tambahkan lock pada `grab_frame()`
   untuk thread safety, sama seperti `predict.py:199`.

10. **`workers/frame_processing_worker.py`** — tambahkan drop-old-frame logic
    pada result_queue agar streaming tidak blocking, sama seperti `predict.py:365`.

11. **`workers/event_broadcast_worker.py`** — migrate `notify_clients()` dari
    `predict.py`. Butuh akses ke list WebSocket connection di `RuntimeState`.

12. **`repositories/capture_repository.py`** — tambahkan `save_image()` agar
    manual reject juga menyimpan JPEG, bukan hanya metadata JSON.

13. **`main.py`** — tambahkan:
    - `CORSMiddleware`
    - `StaticFiles` mount untuk `/captures` → `artifacts/`
    - `startup` event: connect camera, start worker threads, start async broadcast
    - `shutdown` event: disconnect camera

14. **Pastikan file URL konsisten** — `image_url` di semua response harus pakai
    path yang sama dengan route `StaticFiles` yang didaftarkan di `main.py`.
    Frontend supplier-dashboard bergantung pada format URL ini.

## Immediate Next Task

`Lengkapi core/config.py dengan semua env var dari sawit-main/predict.py, lalu migrate hikrobot_camera.py dan webhook_client.py dengan logic aslinya.`

## Decisions Already Agreed

- struktur project memakai flat layer style
- `routes` hanya routing
- `controllers` hanya request/response handling
- `services` hanya orchestration dan business flow
- `repositories` hanya persistence
- `pipelines` hanya inference logic
- `integrations` hanya external system
- `workers` hanya background/realtime loop
- `domain` hanya business rule yang pure
- **migrasi dilakukan dua fase: make it work dulu, baru make it clean**

## Risks / Notes

- Jangan langsung copy-paste seluruh `predict.py` ke satu service baru.
- Prioritaskan pindah per responsibility, bukan per file.
- `predict.py` lama masih dipertahankan dulu sampai wiring baru stabil.
- Camera vendor code harus dipindah hati-hati karena bergantung SDK eksternal.
- Realtime flow perlu diuji bertahap setelah worker dan pipeline mulai tersambung.
- **`VoteTracker` wajib punya flag `processed`** — tanpa ini satu buah bisa
  di-save berkali-kali setelah vote threshold tercapai.
- **Thread safety** — lock wajib ada di `FrameCaptureWorker` saat akses kamera,
  karena endpoint `/api/capture_reject` juga bisa akses kamera secara bersamaan.
- **Queue drop policy** — result_queue harus drop frame lama saat penuh, bukan
  blocking, supaya MJPEG stream tidak hang.

## Suggested Update Format

Setiap ada progress baru, update dokumen ini dengan format:

```text
### YYYY-MM-DD

Done:
- ...

In progress:
- ...

Next:
- ...

Notes:
- ...
```

## Update Log

### 2026-05-18

Done:

- tambah `.env.example` baru di root `ripe-recognition-main`
- sinkronkan env yang dipakai repo baru dengan env lama dari `sawit-main`
- pertahankan env kompatibilitas seperti `RUNNING_PORT` dan section database

In progress:

- persiapan migrasi runtime flow yang masih bergantung camera, worker, dan pipeline

Next:

- review apakah `cli/serve.py` perlu ikut membaca `APP_HOST` dan `APP_PORT`
- lanjut rapikan implementasi phase 1 yang masih placeholder

Notes:

- `APP_PORT` adalah env utama untuk repo baru, `RUNNING_PORT` tetap didukung
- beberapa env masih disimpan untuk kompatibilitas walau belum semua aktif dipakai

### 2026-05-17

Done:

- explore kedua codebase
- simpulkan target arsitektur final
- tulis dokumen `target-architecture.md`
- scaffold struktur baru di `ripe-recognition-main`
- verifikasi syntax skeleton

In progress:

- persiapan refactor logic dari script lama ke layer baru

Next:

- extract config
- extract camera integration
- extract repository untuk result dan capture

Notes:

- `predict.py` lama masih untouched dan aman dipakai sebagai referensi migrasi

---

### 2026-05-18

Done:

- deep analysis seluruh codebase: `sawit-main/predict.py`, semua helper, dan
  semua skeleton file di `ripe-recognition-main/src/`
- konfirmasi bahwa folder structure sudah 100% sesuai target-architecture.md
- identifikasi gap antara skeleton dan implementasi asli
- konfirmasi strategi migrasi dua fase: **make it work dulu, baru make it clean**
- update dokumen ini dengan next steps yang lebih detail dan risks yang eksplisit

In progress:

- tidak ada implementasi yang disentuh, hanya analisis dan perencanaan

Next:

- lengkapi `core/config.py` dengan semua env var yang masih kurang
- migrate Hikrobot SDK ke `integrations/camera/hikrobot_camera.py`
- migrate webhook httpx call ke `integrations/notifications/webhook_client.py`

Notes:

- 5 hal kritis yang tidak boleh terlewat saat Fase 1:
  1. `VoteTracker` butuh field `processed` — tanpa ini ada duplicate saves
  2. `FrameCaptureWorker` butuh `lock` — thread safety dengan endpoint manual
  3. `result_queue` harus drop-old-frame saat penuh, bukan blocking
  4. `RuntimeState` butuh `websocket_clients` list, bukan hanya `active_clients: int`
  5. `image_url` format harus konsisten antara backend response dan StaticFiles mount

---

### 2026-05-18 (sesi 4)

Done:

- Compare `sawit-main` vs `sawit-update-predict-app` — identifikasi perbedaan logic bisnis
- Update seluruh `ripe-recognition-main` agar sesuai dengan `sawit-update` (versi latest):
  - `core/config.py` — hapus cls_model, vote_threshold; tambah `minimum_size=460000`
  - `core/constants.py` — update `ENTRY_MARGIN=100`, tambah `DETECTION_START_X_OFFSET=2200`,
    hapus trunk-related constants
  - `pipelines/model_registry.py` — 2 model → 1 model (`3_class.pt`)
  - `pipelines/realtime_inspection_pipeline.py` — hapus trunk_model, draw_boxes_for_trunk,
    track_trunk; semua kelas (ACC/REJ/TP) dari 1 model
  - `workers/frame_processing_worker.py` — ganti VoteTracker voting → single-trigger detection
    dengan `processed_objects` set + `last_tp` pairing logic + `MINIMUM_SIZE` filter;
    dual JSON save (`_ripeness.json` + `_tp.json`)
  - `repositories/result_repository.py` — rewrite `list_today_results` agar merge
    `_ripeness.json` + `_tp.json` per base_name, sesuai sawit-update
  - `repositories/capture_repository.py` — update payload ke field baru
    (`ripeness_status`, `ripeness_confidence`, `tp_status`, `tp_confidence`)
  - `schemas/inspection_schema.py` — update field ke skema baru
  - `schemas/capture_schema.py` — update field ke skema baru
  - `services/capture_service.py` — hapus pipeline dependency, update event/webhook payload
  - `core/dependencies.py` — hapus `pipeline` param dari `get_capture_service()`
  - `.env` + `.env.example` — hapus CLS_MODEL_SIZE/VERSION, VOTE_THRESHOLD;
    tambah MINIMUM_SIZE; update komentar model

In progress:

- Belum ada

Next:

- Test dengan hardware Hikrobot
- Verifikasi checklist "Verifikasi Akhir"
- Pastikan FE supplier-dashboard bisa baca response format baru
  (`ripeness_status` / `ripeness_confidence` menggantikan `status` / `confidence`)

Notes:

- **Breaking change di response schema** — FE mungkin perlu update jika masih membaca
  field `status` / `confidence` / `prediction`. Field baru: `ripeness_status`,
  `ripeness_confidence`, `tp_status`, `tp_confidence`
- Model sekarang 1 file: `models/release/3_class.pt` (deteksi ACC + REJ + TP sekaligus)
- Tidak ada lagi voting — save langsung saat detection trigger
- TP disave sebagai JSON terpisah (`_tp.json`) tanpa gambar, dipair dengan timestamp buah

---

### 2026-05-18 (sesi 3)

Done:

- Update memory sistem dengan project context, user preferences, dan feedback kritis
- Tulis ulang `README.md` — hilangkan referensi ke `predict.py` lama, tambahkan
  instruksi setup dan run yang benar untuk struktur baru
- Buat `CLAUDE.md` — panduan tim berisi layer constraints, critical invariants,
  naming conventions, dan path rules
- Update `docs/refactor-checklist.md` — centang semua item Fase 1 yang sudah
  diimplementasikan; verifikasi akhir (hardware) masih `[ ]`
- Update status fase di `migration-progress.md`

In progress:

- Tidak ada

Next:

- **Test dengan hardware Hikrobot** — jalankan server, verifikasi semua endpoint
  sesuai checklist "Verifikasi Akhir" di `refactor-checklist.md`
- Verifikasi FE supplier-dashboard bisa connect tanpa perubahan
- Setelah verifikasi OK → nonaktifkan `sawit-main/predict.py` (Phase 1 selesai)
- Phase 2: unit tests, cleanup requirements.txt, pisahkan dev/runtime deps

Notes:

- `CLAUDE.md` siap dibagikan ke tim
- `README.md` sudah tidak referensi `predict.py` lama
- Satu-satunya yang belum di-migrate: `pipelines/trunk_detection_pipeline.py`
  (trunk parse logic sudah inline di `frame_processing_worker`, aman untuk saat ini)

---

### 2026-05-18 (sesi 2)

Done:

- Migrasi penuh semua layer dari `sawit-main/predict.py` ke struktur baru
- `core/config.py` — semua env var lengkap (camera, model, inference, display, webhook, scheduler)
- `core/constants.py` — konstanta display, warna, queue size, reference line
- `domain/voting.py` — `VoteTracker` dengan field `processed` dan `score`
- `domain/entities.py` — `InspectionResult` dengan `title` dan `description` property
- `domain/value_objects.py` — `BoundingBox`, `TrunkBox`, type aliases
- `integrations/camera/hikrobot_camera.py` — full SDK migration (Mono8, BayerRG8, RGB8)
- `integrations/camera/opencv_camera.py` — fallback dev via `cv2.VideoCapture`
- `integrations/notifications/webhook_client.py` — actual `httpx.AsyncClient` call
- `integrations/storage/local_file_storage.py` — tambah `write_image()` via `cv2.imwrite`
- `integrations/scheduler/upload_scheduler.py` — APScheduler + `upload_today_errors` logic
- `workers/runtime_state.py` — tambah `track_history`, `classified_labels`, `lock`,
  `websocket_clients`, `main_loop`
- `pipelines/model_registry.py` — load kedua YOLO model, CUDA half-precision, FileNotFoundError
- `pipelines/realtime_inspection_pipeline.py` — `draw_boxes`, `draw_boxes_for_trunk`,
  `draw_roi`, `track_ripeness`, `track_trunk`
- `workers/frame_capture_worker.py` — lock saat grab_frame, skip jika queue penuh, run_loop
- `workers/frame_processing_worker.py` — full `detect_and_classify` migration: garis referensi,
  voting, save result (JSON + JPEG + errors copy), event_queue push, webhook
- `workers/event_broadcast_worker.py` — `notify_clients` async loop ke WebSocket clients
- `repositories/capture_repository.py` — `save_manual_reject` dengan simpan JPEG + copy errors
- `services/streaming_service.py` — `generate_frames()` generator untuk MJPEG
- `services/capture_service.py` — capture frame dengan lock, push event, kirim webhook
- `controllers/streaming_controller.py` — return `StreamingResponse` dengan MJPEG headers
- `controllers/capture_controller.py` — handle `RuntimeError` → HTTP 500
- `routes/streaming.py` — hapus `response_model` karena StreamingResponse
- `core/dependencies.py` — update wiring `CaptureService` (camera, state, webhook, pipeline),
  tambah `set_camera()` / `get_camera()` untuk injection dari startup
- `main.py` — CORS, StaticFiles mount `/captures` → `artifacts/`, startup lifecycle
  (folder init, camera connect, 3 workers start, scheduler start), shutdown lifecycle,
  WebSocket `/ws/results` route
- Syntax check 33 file — semua OK

In progress:

- Belum ada (semua Fase 1 selesai secara kode)

Next:

- Test server startup dengan hardware Hikrobot terpasang
- Verifikasi semua endpoint satu per satu (lihat checklist `refactor-checklist.md`)
- Pastikan FE supplier-dashboard bisa connect tanpa perubahan

Notes:

- `predict.py` lama masih aman di `sawit-main/` sebagai referensi
- `image_url` format: `captures/results/{date}/{timestamp}_auto.jpg` — konsisten dengan
  StaticFiles mount di `main.py` (`/captures` → `artifacts/`)
- `get_capture_service()` tidak pakai `@lru_cache` karena butuh akses `_camera` global
  yang diset saat startup, bukan saat import
