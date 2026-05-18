# Target Architecture

## Goal

Dokumen ini jadi acuan final untuk migrasi isi `sawit-main` ke
`ripe-recognition-main`.

Tujuan utamanya:

- struktur project mudah dipahami tim
- route, controller, service, repository punya boundary yang jelas
- logic realtime inference, hardware camera, webhook, dan file storage tidak
  numpuk di satu file
- project tetap gampang di-maintain dan scalable tanpa over-engineering

## Final Folder Structure

```text
ripe-recognition-main/
  src/
    ripe_recognition/
      main.py

      routes/
        health.py
        inspection.py
        streaming.py
        capture.py
        truck.py

      controllers/
        health_controller.py
        inspection_controller.py
        streaming_controller.py
        capture_controller.py
        truck_controller.py

      services/
        health_service.py
        inspection_service.py
        streaming_service.py
        capture_service.py
        truck_service.py
        result_service.py

      repositories/
        result_repository.py
        capture_repository.py
        truck_repository.py

      pipelines/
        realtime_inspection_pipeline.py
        detect_only_pipeline.py
        detect_then_classify_pipeline.py
        trunk_detection_pipeline.py
        model_registry.py

      integrations/
        camera/
          base.py
          hikrobot_camera.py
          opencv_camera.py
        notifications/
          webhook_client.py
        storage/
          local_file_storage.py
        scheduler/
          upload_scheduler.py

      workers/
        frame_capture_worker.py
        frame_processing_worker.py
        event_broadcast_worker.py
        runtime_state.py

      domain/
        entities.py
        value_objects.py
        rules.py
        voting.py
        events.py

      schemas/
        inspection_schema.py
        capture_schema.py
        truck_schema.py
        common_schema.py

      core/
        config.py
        logging.py
        exceptions.py
        dependencies.py
        constants.py

  cli/
    serve.py
    predict_detect.py
    predict_pipeline.py
    train_detect.py
    train_classify.py

  models/
    release/
    experiments/

  artifacts/
    captures/
    results/
    logs/

  tests/
    unit/
    integration/
```

## Layer Responsibilities

### `routes/`

Hanya untuk deklarasi endpoint dan wiring `APIRouter`.

- tidak boleh ada logic inference
- tidak boleh ada akses repository
- tidak boleh ada business rule

Contoh:

- `POST /api/capture_reject`
- `GET /api/video_feed`
- `GET /api/results_today`

### `controllers/`

Controller hanya bertugas:

- menerima request
- memanggil service
- mengubah hasil service menjadi response/schema

Controller tidak boleh:

- query database
- baca tulis file
- panggil model YOLO langsung
- pegang queue atau worker state langsung

### `services/`

Service adalah orchestration layer.

Service boleh:

- menggabungkan beberapa repository
- memanggil pipeline inferensi
- memanggil integration seperti webhook atau camera abstraction
- menjalankan business flow

Service tidak boleh:

- query data langsung ke DB/file
- isi SQL
- tahu detail SDK vendor camera

### `repositories/`

Repository khusus untuk persistence.

Contohnya:

- baca metadata hasil inspection dari file JSON
- simpan capture result
- simpan atau ambil truck state

Repository tidak boleh berisi:

- rule PASS/FAIL
- logic voting
- logic HTTP
- logic model inference

### `pipelines/`

Pipeline berisi logic inferensi dan pemrosesan frame.

Contoh:

- YOLO realtime tracking
- detect-only flow
- detect + classify flow
- trunk detection flow

Pipeline fokus ke image/frame processing, bukan ke API.

### `integrations/`

Tempat semua koneksi ke dunia luar.

Contoh:

- Hikrobot SDK
- OpenCV camera source
- webhook client
- local storage
- scheduler

Folder ini cocok untuk code yang sulit ditest secara pure karena tergantung
driver, network, atau filesystem.

### `workers/`

Worker untuk proses background dan realtime runtime.

Contoh:

- capture frame loop
- process frame loop
- broadcast websocket event
- shared runtime state

Ini penting supaya logic threaded/queued tidak bercampur dengan HTTP layer.

### `domain/`

Domain adalah rule bisnis murni.

Contoh:

- voting threshold
- penentuan status PASS/FAIL
- event payload shape
- entity untuk inspection result

Rule di sini idealnya pure function atau object sederhana yang mudah ditest.

### `schemas/`

Schema request/response untuk FastAPI dan validasi payload.

### `core/`

Shared foundation:

- config/env
- logging
- constants
- dependency wiring
- common exceptions

## Request Flow

Flow standar yang harus dijaga:

```text
route -> controller -> service -> repository / pipeline / integration
```

Contoh:

```text
routes/inspection.py
  -> controllers/inspection_controller.py
  -> services/inspection_service.py
  -> pipelines/realtime_inspection_pipeline.py
  -> repositories/result_repository.py
  -> integrations/notifications/webhook_client.py
```

## Rules of Thumb

Supaya struktur ini tetap sehat, pakai aturan ini:

1. Route hanya routing.
2. Controller hanya menerima request dan mengembalikan response.
3. Service berisi orchestration dan business flow.
4. Repository hanya urus persistence.
5. Pipeline hanya urus inference/frame processing.
6. Integration hanya urus external system.
7. Worker hanya urus loop background dan queue runtime.
8. Domain hanya urus business rules yang pure.

## Mapping from Current `sawit-main`

### `predict.py`

Dipecah menjadi beberapa bagian:

- `routes/inspection.py`
- `routes/streaming.py`
- `routes/capture.py`
- `routes/truck.py`
- `controllers/inspection_controller.py`
- `controllers/streaming_controller.py`
- `controllers/capture_controller.py`
- `controllers/truck_controller.py`
- `services/inspection_service.py`
- `services/streaming_service.py`
- `services/capture_service.py`
- `services/truck_service.py`
- `repositories/result_repository.py`
- `repositories/capture_repository.py`
- `pipelines/realtime_inspection_pipeline.py`
- `pipelines/trunk_detection_pipeline.py`
- `workers/frame_capture_worker.py`
- `workers/frame_processing_worker.py`
- `workers/event_broadcast_worker.py`
- `workers/runtime_state.py`
- `domain/voting.py`
- `domain/rules.py`

### `helpers/hikrobot_camera.py`

Pindah ke:

- `integrations/camera/hikrobot_camera.py`

Tambahkan abstraction:

- `integrations/camera/base.py`

### `helpers/webhook.py`

Pindah ke:

- `integrations/notifications/webhook_client.py`

### `helpers/uploader.py`

Pindah ke:

- `integrations/storage/local_file_storage.py`

Jika nanti storage semakin kompleks, sebagian persistence metadata bisa
dipisahkan lagi ke repository.

### `helpers/scheduler.py`

Pindah ke:

- `integrations/scheduler/upload_scheduler.py`

### `predict_obj_detect.py`

Pindah ke:

- `cli/predict_detect.py`
- `pipelines/detect_only_pipeline.py`

### `predict_sep.py`

Pindah ke:

- `cli/predict_pipeline.py`
- `pipelines/detect_then_classify_pipeline.py`

### `train_obj_detect.py`

Pindah ke:

- `cli/train_detect.py`

### `train_obj_clas.py`

Pindah ke:

- `cli/train_classify.py`

## Why This Structure Fits This Project

Struktur ini dipilih karena:

- paling gampang dipahami tim yang familiar dengan Express.js
- tetap cocok untuk FastAPI
- cukup rapi untuk project CV/ML realtime
- tidak terlalu rumit seperti microservice
- enak untuk migrasi bertahap dari script-based project

## Migration Plan

### Phase 1

Siapkan pondasi:

- buat `src/ripe_recognition/`
- buat `main.py`
- buat folder `routes`, `controllers`, `services`, `repositories`,
  `pipelines`, `integrations`, `workers`, `domain`, `schemas`, `core`

### Phase 2

Pindahkan shared foundation:

- config/env ke `core/config.py`
- logging ke `core/logging.py`
- constants/magic number ke `core/constants.py`

### Phase 3

Pisahkan integration:

- camera adapter
- webhook client
- local storage
- scheduler

### Phase 4

Extract business and pipeline logic:

- voting rule
- PASS/FAIL rule
- realtime inspection pipeline
- trunk pipeline

### Phase 5

Pindahkan API layer:

- route
- controller
- service
- repository

### Phase 6

Rapikan tooling:

- pecah dependency runtime dan development
- tambah unit test untuk voting dan status rule
- tambah integration test untuk endpoint utama

## Non-Goals

Hal yang tidak perlu dilakukan di fase awal:

- tidak perlu microservice
- tidak perlu repository database kalau data masih file-based
- tidak perlu event bus kompleks
- tidak perlu generic abstraction berlebihan

## Final Decision

Keputusan final untuk project ini:

- gunakan struktur flat per layer
- `routes/*.py` hanya routing
- `controllers/*.py` hanya handle request/response
- `services/*.py` hanya orchestration/business flow
- `repositories/*.py` hanya persistence
- `integrations/*` untuk external system
- `pipelines/*` untuk model inference
- `workers/*` untuk realtime loop/background jobs
- `domain/*` untuk business rules murni

Struktur ini menjadi target resmi untuk proses migrasi dari `sawit-main` ke
`ripe-recognition-main`.
