# Refactor Checklist — ripe-recognition-main

Tujuan: migrasi semua logic dari `sawit-main/predict.py` ke struktur baru
tanpa mengubah behavior sedikit pun.

Status: **Fase 1 (Make it Work) selesai secara kode — 2026-05-18.**
Item dengan `[x]` sudah diimplementasikan dan lolos syntax check.
Item dengan `[ ]` masih butuh verifikasi dengan hardware / runtime.

---

## Foundation

- [x] **`core/config.py`** — tambahkan env var yang masih kurang:
  - [x] `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS`
  - [x] `MODEL_SIZE`, `MODEL_VERSION`
  - [x] `CLS_MODEL_SIZE`, `CLS_MODEL_VERSION`
  - [x] `CONF_THRESHOLD`, `VOTE_THRESHOLD`
  - [x] `BORDER_THICKNESS`, `FONT_SCALE`, `FONT_THICKNESS`
  - [x] `ROI_SCALE`
  - [x] `BACKEND_URL`, `BACKEND_API_VER`, `WEBHOOK_SECRET`
  - [x] `UPLOAD_HOUR`, `UPLOAD_MINUTE`, `DESTINATION_UPLOAD`

- [x] **`core/constants.py`** — tambahkan konstanta display yang masih kurang:
  - [x] `RIPENESS_MODEL_PATH` dan `TRUNK_MODEL_PATH` default path
  - [x] Warna bounding box (PASS/FAIL)

---

## Domain

- [x] **`domain/voting.py`** — `VoteTracker`:
  - [x] Tambah field `score: float = 0.0`
  - [x] Tambah field `processed: bool = False` — kunci agar satu buah tidak
        di-save berkali-kali setelah vote threshold tercapai
  - [x] Method `register()` harus update `score` bersamaan dengan `label`

- [x] **`domain/rules.py`** — verifikasi `derive_status()` sudah identik
      dengan logika di `predict.py:305`

- [x] **`domain/entities.py`** — definisikan dataclass untuk:
  - [x] `InspectionResult` (prediction, confidence, status, truck_id,
        bounding_box, trunk_box, timestamp, image_url, capture_type)

- [x] **`domain/value_objects.py`** — definisikan:
  - [x] `BoundingBox` (x_min, y_min, x_max, y_max)
  - [x] `TrunkBox` (label, score, x_min, y_min, x_max, y_max)

---

## Integrations

- [x] **`integrations/camera/base.py`** — verifikasi interface sudah ada:
  - [x] `connect()`, `grab_frame()`, `disconnect()`

- [x] **`integrations/camera/hikrobot_camera.py`** — migrate actual SDK:
  - [x] Import semua dari `MvImport` (MvCamera, MV_CC_DEVICE_INFO, dll)
  - [x] `connect()`: enum devices, create handle, open device, start grabbing
  - [x] `grab_frame()`: GetOneFrameTimeout, decode pixel format
    - [x] Handle `Mono8` → `COLOR_GRAY2BGR`
    - [x] Handle `BayerRG8` → `COLOR_BAYER_RGGB2BGR_EA`
    - [x] Handle `RGB8_Packed` (17301513) → `COLOR_RGB2BGR`
  - [x] `disconnect()`: stop grabbing, close device, destroy handle

- [x] **`integrations/camera/opencv_camera.py`** — implementasi fallback
      untuk development tanpa hardware Hikrobot:
  - [x] Baca dari webcam atau video file via `cv2.VideoCapture`

- [x] **`integrations/notifications/webhook_client.py`** — migrate actual
      httpx call:
  - [x] `send_quality_event()` harus async, pakai `httpx.AsyncClient`
  - [x] Set header `Content-Type: application/json`
  - [x] Set header `x-webhook-secret` dari config
  - [x] POST ke `{BACKEND_URL}{BACKEND_API_VER}/webhooks/qualitycontrols`
  - [x] Handle exception dengan silent fail (log debug, jangan crash)

- [x] **`integrations/storage/local_file_storage.py`** — tambahkan method:
  - [x] `write_image(path, frame, quality=80)` — wrapper `cv2.imwrite`
  - [x] `ensure_dir()` dipanggil sebelum write (sudah ada, verifikasi)

- [x] **`integrations/scheduler/upload_scheduler.py`** — migrate APScheduler:
  - [x] `start()`: buat `BackgroundScheduler`, tambah job cron `upload_today_errors`
  - [x] `stop()`: `scheduler.shutdown()`
  - [x] `atexit.register` untuk shutdown otomatis

- [x] **`integrations/scheduler/`** — migrate logic `uploader.py`:
  - [x] `upload_today_errors()`: copy folder results + errors ke DESTINATION_UPLOAD
  - [x] Handle path collision dengan suffix `_1`, `_2`, dst
  - [x] `shutil.copytree` lalu `shutil.rmtree` source

---

## Workers

- [x] **`workers/runtime_state.py`** — tambahkan field yang masih kurang:
  - [x] `track_history: dict` — akumulasi vote per track_id
  - [x] `classified_labels: dict` — label + score final per track_id
  - [x] `lock: threading.Lock` — untuk thread-safe akses kamera
  - [x] `websocket_clients: list` — list WebSocket connection aktif
  - [x] `main_loop: asyncio.AbstractEventLoop | None` — untuk
        `run_coroutine_threadsafe` dari thread ke async

- [x] **`workers/frame_capture_worker.py`**:
  - [x] `run_once()` harus acquire `state.lock` saat `grab_frame()`
  - [x] Skip jika `frame_queue` sudah penuh (jangan blocking put)
  - [x] Tambah `time.sleep(0.001)` setelah tiap iterasi

- [x] **`workers/frame_processing_worker.py`**:
  - [x] Migrate full logic dari `detect_and_classify()` di `predict.py`:
    - [x] Ambil frame dari `frame_queue`
    - [x] Jalankan `model.track()` untuk kematangan
    - [x] Jalankan `trunk_model.track()` untuk tangkai
    - [x] Parse trunk bounding box
    - [x] Gambar garis referensi kiri-kanan (line_left, line_right)
    - [x] Loop tiap box: cek track_id, cek posisi vs garis referensi
    - [x] Register ke `VoteTracker`, skip jika `processed=True`
    - [x] Jika vote tembus threshold:
      - [x] Tentukan status via `derive_status()`
      - [x] Simpan JPEG via `local_file_storage.write_image()`
      - [x] Simpan metadata JSON via `local_file_storage.write_json()`
      - [x] Push ke `event_queue`
      - [x] Kirim webhook via `run_coroutine_threadsafe`
    - [x] Encode stream frame ke JPEG, push ke `result_queue`
    - [x] Drop frame lama dari `result_queue` jika penuh (non-blocking)

- [x] **`workers/event_broadcast_worker.py`**:
  - [x] Migrate `notify_clients()` dari `predict.py:390-399`
  - [x] Loop `event_queue`, kirim JSON ke semua `websocket_clients`
  - [x] Handle disconnect: hapus client dari list jika send gagal
  - [x] `asyncio.sleep(0.05)` antar iterasi

---

## Pipelines

- [x] **`pipelines/model_registry.py`**:
  - [x] Load model ripeness: `YOLO(ripeness_model_path)`
  - [x] Load model trunk: `YOLO(trunk_model_path)`
  - [x] Deteksi device: `cuda` atau `cpu`
  - [x] Jika CUDA: `.to(device).half()` untuk kedua model
  - [x] Raise `FileNotFoundError` jika model tidak ditemukan
  - [x] Suppress ultralytics logging: `logging.getLogger("ultralytics").setLevel(WARNING)`

- [x] **`pipelines/realtime_inspection_pipeline.py`**:
  - [x] Expose `model` dan `trunk_model` dari `ModelRegistry`
  - [x] Method `draw_boxes(frame, results)` — gambar bounding box kematangan
    - [x] Warna merah jika `"rej" in label.lower()`, hijau jika tidak
    - [x] Tampilkan label + confidence
    - [x] Override label/score dari `classified_labels` jika ada
  - [x] Method `draw_boxes_for_trunk(frame, results)` — gambar bounding box tangkai
    - [x] Warna hijau jika `"Acc"`, biru jika tidak
    - [x] Rename `"Acc"` → `"Tangkai panjang"` saat display
  - [x] Method `draw_roi(frame)` dan `draw_roi_for_trunk(frame)`

- [ ] **`pipelines/trunk_detection_pipeline.py`**:
  - [ ] Method untuk parse trunk result menjadi `TrunkBox`
  *(belum dimigrasi — logic sudah inline di frame_processing_worker)*

---

## Repositories

- [x] **`repositories/result_repository.py`**:
  - [x] `list_today_results()` — baca semua `.json` dari `results/{today}/`
  - [x] Pastikan response shape match dengan `InspectionResultResponse` schema

- [x] **`repositories/capture_repository.py`**:
  - [x] `save_auto_result(frame, prediction, confidence, status, truck_id,
        bounding_box, trunk_box)`:
    - [x] Buat folder `results/{date}/` jika belum ada
    - [x] Simpan JPEG dengan suffix `_auto`
    - [x] Simpan metadata JSON
    - [x] Jika status FAIL: duplikasi ke folder `errors/{date}/`
    - [x] Return `(date_folder, timestamp)`
  - [x] `save_manual_reject(frame, truck_id)`:
    - [x] Simpan JPEG dengan suffix `_manual`
    - [x] Simpan metadata JSON
    - [x] Return full result object (sesuai `IResultResponse` yang diharapkan FE)

- [x] **`repositories/truck_repository.py`** — sudah selesai, verifikasi:
  - [x] `get_current_truck_id()` → baca dari `RuntimeState`
  - [x] `set_current_truck_id(truck_id)` → tulis ke `RuntimeState`

---

## Services

- [x] **`services/inspection_service.py`**:
  - [x] `get_runtime_status()` — status pipeline + model loaded atau tidak

- [x] **`services/result_service.py`**:
  - [x] `list_today()` → delegate ke `ResultRepository.list_today_results()`
  - [x] Format response menjadi list `InspectionResultResponse`

- [x] **`services/streaming_service.py`**:
  - [x] `generate_frames()` — generator untuk MJPEG stream
  - [x] Baca dari `result_queue`, yield frame bytes
  - [x] Skip (sleep 0.01) jika queue kosong

- [x] **`services/capture_service.py`**:
  - [x] `manual_reject()`:
    - [x] Ambil frame dari kamera via lock
    - [x] Delegate simpan ke `CaptureRepository.save_manual_reject()`
    - [x] Push ke `event_queue`
    - [x] Kirim webhook async
    - [x] Return hasil sesuai `IResultResponse`

- [x] **`services/truck_service.py`**:
  - [x] `set_truck(truck_id)` → delegate ke `TruckRepository`
  - [x] Return `SetTruckResponse`

- [x] **`services/health_service.py`**:
  - [x] `get_status()` → return server info + model status

---

## Controllers

- [x] **`controllers/streaming_controller.py`**:
  - [x] `get_video_feed(service)` → return `StreamingResponse` dengan
        `generate_frames()` dan header MJPEG yang benar

- [x] **`controllers/inspection_controller.py`**:
  - [x] `get_results_today(service)` → return list hasil hari ini

- [x] **`controllers/capture_controller.py`**:
  - [x] `capture_reject(service)` → panggil service, return `CaptureRejectResponse`

- [x] **`controllers/truck_controller.py`**:
  - [x] `set_truck(request, service)` → panggil service, return `SetTruckResponse`

- [x] **`controllers/health_controller.py`**:
  - [x] `health_check(service)` → return status

---

## Routes

Verifikasi semua route sudah benar (path, method, response model):

- [x] **`routes/streaming.py`** — `GET /api/video_feed`
- [x] **`routes/inspection.py`** — `GET /api/results_today`
- [x] **`routes/capture.py`** — `POST /api/capture_reject`
- [x] **`routes/truck.py`** — `POST /api/set_truck`
- [x] **`routes/health.py`** — `GET /health`

---

## Schemas

Verifikasi semua schema match dengan apa yang diharapkan FE:

- [x] **`schemas/inspection_schema.py`** — `InspectionResultResponse`:
  - [x] `id`, `status`, `title`, `description`, `timestamp`
  - [x] `image_url`, `capture_type`, `truck_id`
  - [x] `prediction`, `confidence`
  - [x] `bounding_box`, `trunk_box`

- [x] **`schemas/capture_schema.py`** — `CaptureRejectResponse`:
  - [x] Harus return full object, bukan hanya `{"message": "..."}`
  - [x] Field sesuai `IResultResponse` di FE

- [x] **`schemas/truck_schema.py`** — `SetTruckResponse`:
  - [x] `message: str`
  - [x] `truck_id: str`

- [x] **`schemas/common_schema.py`** — `ApiMessage`:
  - [x] `message: str`

---

## App Wiring (`main.py`)

- [x] Tambah `CORSMiddleware`:
  - [x] `allow_origins=[settings.frontend_url]`
  - [x] `allow_credentials=True`
  - [x] `allow_methods=["*"]`
  - [x] `allow_headers=["*"]`

- [x] Tambah `StaticFiles` mount:
  - [x] `/captures` → `artifacts/` directory
  - [x] Pastikan path ini konsisten dengan `image_url` yang di-return di response

- [x] Tambah `startup` event:
  - [x] Load `.env` via `load_dotenv()`
  - [x] Buat folder `artifacts/captures`, `artifacts/results`, `artifacts/errors`
  - [x] Connect kamera: `get_camera()` / `camera.connect()`
  - [x] Simpan `main_loop = asyncio.get_running_loop()` ke `RuntimeState`
  - [x] Start `asyncio.create_task(event_broadcast_worker.run_loop())`
  - [x] Start `threading.Thread(target=frame_capture_worker.run_loop, daemon=True)`
  - [x] Start `threading.Thread(target=frame_processing_worker.run_loop, daemon=True)`
  - [x] Start scheduler: `upload_scheduler.start()`

- [x] Tambah `shutdown` event:
  - [x] Disconnect kamera: `camera.disconnect()`
  - [x] Stop scheduler: `upload_scheduler.stop()`

---

## CLI

- [x] **`cli/serve.py`** — entrypoint untuk run server:
  - [x] Parse args (`--port`, `--host`, dll)
  - [x] Call `uvicorn.run("src.ripe_recognition.main:app", ...)`

---

## Verifikasi Akhir (sebelum cut-over dari sawit-main)

*Perlu hardware Hikrobot terpasang untuk verifikasi items di bawah.*

- [ ] Server bisa distart tanpa error
- [ ] `GET /health` return 200
- [ ] `GET /api/video_feed` tampil di browser sebagai video stream
- [ ] `GET /api/results_today` return array (kosong atau berisi data)
- [ ] `POST /api/set_truck` dengan `{"truck_id": "TEST"}` return sukses
- [ ] `POST /api/capture_reject` return full JSON object (bukan hanya message)
- [ ] Hasil auto detection tersimpan di `artifacts/results/{date}/`
- [ ] Webhook terkirim ke Node.js API setiap ada detection
- [ ] Static file bisa diakses: `http://localhost:8000/captures/results/{date}/file.jpg`
- [ ] WebSocket `/ws/results` bisa connect dan terima event
- [ ] FE supplier-dashboard bisa connect ke BE baru tanpa perubahan
- [ ] Scheduler upload berjalan sesuai `UPLOAD_HOUR:UPLOAD_MINUTE`
