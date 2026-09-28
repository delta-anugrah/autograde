# Architecture: autograde

Dokumen ini adalah acuan desain arsitektur `autograde`.
Struktur ini sudah diimplementasikan: bukan target, ini adalah kondisi saat ini.

---

## Prinsip Desain

- Struktur flat per layer, familiar bagi tim yang kenal Express.js
- Setiap layer punya boundary ketat: tidak boleh ada logic yang salah lapisan
- Cocok untuk project CV/ML realtime tanpa over-engineering
- Mudah untuk onboarding dan maintenance

---

## Folder Structure

```
autograde/
  src/
    palmgrade/
      main.py                    # FastAPI app factory + middleware + lifecycle

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
        model_registry.py

      integrations/
        camera/
          base.py
          hikrobot_camera.py
          opencv_camera.py
          photo_camera.py
        notifications/
          webhook_client.py
        storage/
          local_file_storage.py
        scheduler/
          upload_scheduler.py

      workers/
        frame_capture_worker.py
        frame_processing_worker.py
        capture_save_worker.py
        event_broadcast_worker.py
        runtime_state.py

      domain/
        entities.py
        value_objects.py
        rules.py

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

      license/
        types.py
        local_repo.py
        sync_client.py
        manager.py
        guard.py

  models/
    release/                     # .pt files — tidak di-commit ke git
  artifacts/                     # Output runtime — tidak di-commit ke git
  tests/
    unit/
    integration/
```

---

## Layer Responsibilities

### `routes/`

Hanya deklarasi endpoint dan wiring `APIRouter`.

- Boleh: path, method, `Depends()`, return type hint
- Dilarang: logic apapun, akses file, akses model, akses queue

---

### `controllers/`

Terima request, panggil service, return response.

- Boleh: terima request, panggil satu service, handle `HTTPException`
- Dilarang: akses repository langsung, akses queue, panggil YOLO

---

### `services/`

Orchestration layer: menggabungkan repository, pipeline, dan integration.

- Boleh: gabungkan repo + pipeline + integration, jalankan business flow
- Dilarang: SQL, detail SDK vendor, akses file langsung, return HTTP response

---

### `repositories/`

Persistence layer: baca/tulis file JSON dan WebP.

- Boleh: baca/tulis file via `LocalFileStorage`
- Dilarang: rule PASS/FAIL, logic HTTP, logic model inference

---

### `pipelines/`

YOLO inference dan frame processing.

- Boleh: YOLO inference, draw bounding box, frame analysis
- Dilarang: HTTP call, file save, business rule

---

### `integrations/`

Koneksi ke sistem eksternal.

- `camera/`: Hikrobot SDK / OpenCV / Photo (dev mode)
- `notifications/`: webhook httpx client
- `storage/`: local file read/write
- `scheduler/`: APScheduler daily cron

---

### `workers/`

Background loop dan shared runtime state.

- Boleh: loop thread/asyncio, akses queue, hold lock, akses `RuntimeState`
- Dilarang: langsung return HTTP response, langsung simpan ke file

---

### `domain/`

Business rule murni: zero I/O.

- Boleh: pure function, pure dataclass
- Dilarang: import `cv2`, `fastapi`, `httpx`; baca/tulis file

---

### `license/`

License guard: opsional. Hanya aktif jika `LICENSE_ENABLED=true`.

- `guard.py`: `BaseHTTPMiddleware`, registered di `create_app()`
- `gate.py`: aturan murni yang menghentikan thread grading (yang sebenarnya menghentikan pabrik)
- `manager.py`: Ed25519 JWS verify `LICENSE_TOKEN` + state machine
- `local_repo.py`: penanda batas atas jam (anti tanggal mundur), SQLite
- `sync_client.py`: httpx POST ke license server

---

## Request Flow

```
route → controller → service → repository / pipeline / integration
```

Contoh flow grading:
```
routes/inspection.py
  → controllers/inspection_controller.py
  → services/inspection_service.py
  → pipelines/realtime_inspection_pipeline.py
  → repositories/result_repository.py
  → integrations/notifications/webhook_client.py
```

---

## Rules of Thumb

1. Route hanya routing
2. Controller hanya request/response
3. Service hanya orchestration
4. Repository hanya persistence
5. Pipeline hanya inference/frame processing
6. Integration hanya external system
7. Worker hanya background loop dan queue
8. Domain hanya business rule murni

---

## Why This Structure

- Familiar bagi tim yang kenal Express.js (controller/service/repository)
- Cocok untuk FastAPI
- Cukup rapi untuk project CV/ML realtime
- Tidak terlalu kompleks seperti microservice
- Mudah untuk migrasi bertahap dari script-based codebase
