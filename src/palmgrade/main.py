from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.dependencies import (
    get_capture_repository,
    get_outbox_store,
    get_realtime_inspection_pipeline,
    get_runtime_state,
    get_settings,
    get_webhook_client,
    set_camera,
)
from .integrations.outbox.outbox_store import OutboxStore
from .routes.internal import router as internal_router
from .workers.outbox_retry_worker import OutboxRetryWorker
from .core.logging import configure_logging
from .integrations.camera.base import CameraSource
from .integrations.camera.hikrobot_camera import HikrobotCamera
from .integrations.camera.opencv_camera import OpenCVCamera
from .integrations.camera.photo_camera import PhotoCamera
from .license.guard import LicenseGuardMiddleware
from .license.local_repo import LicenseLocalRepo
from .license.manager import LicenseManager
from .license.sync_client import SyncClient
from .plc import shutdown_plc_worker, start_plc_worker
from .integrations.scheduler.upload_scheduler import UploadScheduler
from .integrations.upload.r2_uploader import R2Uploader
from .integrations.upload.upload_manifest import UploadManifest
from .workers.batch_upload_worker import BatchUploadWorker
from .routes.capture import router as capture_router
from .routes.health import router as health_router
from .routes.inspection import router as inspection_router
from .routes.streaming import router as streaming_router
from .routes.truck import router as truck_router
from .workers.display_worker import DisplayWorker
from .workers.event_broadcast_worker import EventBroadcastWorker
from .workers.frame_capture_worker import FrameCaptureWorker
from .workers.frame_processing_worker import FrameProcessingWorker

load_dotenv(override=False)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    _lic_manager: LicenseManager | None = None
    if settings.lic_enabled:
        _lic_repo = LicenseLocalRepo(settings.artifacts_dir / "license.db")
        _lic_sync = SyncClient(settings.lic_server_url, settings.lic_api_key)
        _lic_manager = LicenseManager(settings.lic_pubkey_pem, _lic_repo, _lic_sync)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if _lic_manager:
            await _lic_manager.init()

        for folder in [settings.captures_dir, settings.results_dir, settings.errors_dir, settings.logs_dir]:
            folder.mkdir(parents=True, exist_ok=True)

        # Fail-fast kalau secret masih default di production (dev tetap boleh,
        # cuma warning). Lihat Settings.validate_for_runtime().
        settings.validate_for_runtime()

        # Init kamera — dikontrol lewat env var CAMERA_TYPE
        # hikrobot (default) = Hikrobot industrial camera (butuh SDK + hardware)
        # opencv              = Webcam atau video file via OpenCV
        # photo               = Single image untuk testing (frame dikembalikan terus)
        camera_type = settings.camera_type.lower()
        if camera_type == "opencv":
            opencv_source: int | str = (
                settings.camera_video_path if settings.camera_video_path else settings.camera_device_index
            )
            camera: CameraSource = OpenCVCamera(
                source=opencv_source,
                width=settings.camera_width,
                height=settings.camera_height,
                fps=settings.camera_fps,
                is_video_file=bool(settings.camera_video_path),
            )
        elif camera_type == "photo":
            camera = PhotoCamera(path=settings.camera_photo_path)
        else:
            camera = HikrobotCamera()

        try:
            camera.connect(index=settings.camera_device_index, serial=settings.camera_serial, feature_file=settings.camera_feature_file)
        except RuntimeError as exc:
            if camera_type == "hikrobot":
                logger.warning("Camera not found at startup: %s — FrameCaptureWorker will keep retrying", exc)
            else:
                raise
        set_camera(camera)

        state = get_runtime_state()
        state.main_loop = asyncio.get_running_loop()

        pipeline = get_realtime_inspection_pipeline()
        storage_instance = get_capture_repository().storage
        webhook = get_webhook_client()

        broadcast_worker = EventBroadcastWorker(state=state)
        asyncio.create_task(broadcast_worker.run_loop())

        def _start_worker(name: str, target_fn) -> threading.Thread:
            t = threading.Thread(target=target_fn, daemon=True, name=name)
            t.start()
            return t

        capture_worker = FrameCaptureWorker(camera=camera, state=state, target_fps=settings.camera_fps, device_index=settings.camera_device_index, serial=settings.camera_serial, feature_file=settings.camera_feature_file)
        display_worker = DisplayWorker(
            state=state,
            pipeline=pipeline,
            settings=settings,
            target_fps=settings.stream_fps or 12,
        )
        processing_worker = FrameProcessingWorker(
            pipeline=pipeline,
            state=state,
            storage=storage_instance,
            webhook=webhook,
            settings=settings,
            outbox_store=get_outbox_store(),
        )

        state.worker_threads = [
            ("capture", _start_worker("capture", capture_worker.run_loop), capture_worker),
            ("display", _start_worker("display", display_worker.run_loop), display_worker),
            ("processing", _start_worker("processing", processing_worker.run_loop), processing_worker),
        ]

        # OutboxRetryWorker — kirim event ke API di BACKEND_URL, poll 1 detik.
        # Ini jalur realtime untuk operator (Grading History + gambar). Batch
        # upload R2 ke cloud (UPLOAD_API_URL) jalan terpisah dan tidak diganggu:
        # event_id-nya sama, jadi kalaupun keduanya menunjuk API yang sama, yang
        # kedua dibalas already_processed.
        #
        # PENTING: BACKEND_URL harus API LOKAL (http://<ip-pc>:2500), bukan
        # api.smagri.id. Menunjuk cloud dari sini yang membanjiri produksi
        # dengan ~1098 event tes pada 2026-08-09.
        outbox_worker = OutboxRetryWorker(
            outbox=get_outbox_store(),
            settings=settings,
            state=state,
        )
        outbox_thread = _start_worker("outbox_retry", outbox_worker.run_loop)
        state.worker_threads.append(("outbox_retry", outbox_thread, outbox_worker))

        # PLC — sinyal grading ke PLC lewat coupler ODOT (Modbus-TCP).
        # Mengembalikan None kalau PLC_ENABLED=false, jadi di cloud dan di PC
        # dev tidak ada thread tambahan sama sekali. Didaftarkan ke
        # worker_threads supaya ikut di-restart watchdog 10 detik kalau mati.
        # `settings` dan `camera` di lambda ini closure-local milik
        # `create_app`/`lifespan`, bukan module-level. Aman karena `camera`
        # di-assign ulang dari `get_camera()` di scope yang sama, dan
        # `core/dependencies.py` menyimpannya sebagai satu singleton.
        if (plc_worker := start_plc_worker(settings, health_check=lambda: camera.connected)) is not None:
            state.worker_threads.append(("plc", _start_worker("plc", plc_worker.run_loop), plc_worker))

        async def _watchdog() -> None:
            while True:
                await asyncio.sleep(10)
                for i, (name, thread, worker) in enumerate(state.worker_threads):
                    if not thread.is_alive():
                        logger.error("Worker thread '%s' died — restarting", name)
                        new_thread = _start_worker(name, worker.run_loop)
                        state.worker_threads[i] = (name, new_thread, worker)

        asyncio.create_task(_watchdog())

        # Batch upload cloud: gambar → R2, teks → API cloud, tiap jam.
        upload_manifest = UploadManifest(db_path=settings.state_dir / "upload_manifest.db")
        r2_uploader = R2Uploader(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
        )
        batch_worker = BatchUploadWorker(
            settings=settings, manifest=upload_manifest, uploader=r2_uploader
        )
        upload_scheduler = UploadScheduler(settings=settings, run_batch=batch_worker.run_batch_once)
        upload_scheduler.start()

        yield

        from .core.dependencies import get_camera

        # PLC didahulukan: saat SIGTERM tiba, coil OK/NG punya peluang ~2 dari 3
        # sedang ON di tengah pulse (200ms ON dalam siklus 300ms). Kontrak coil
        # itu "satu pulse = satu buah" — dibiarkan ON sampai watchdog ODOT
        # menyerah (masih 30 detik) berarti PLC menyortir banyak buah dengan
        # keputusan basi. Digarap best-effort: gagal di sini tidak boleh
        # menghalangi sisa shutdown.
        try:
            plc_thread = next((t for name, t, _ in state.worker_threads if name == "plc"), None)
            shutdown_plc_worker(plc_thread)
        except Exception:
            logger.exception("Shutdown PLC gagal — shutdown lain tetap dilanjutkan")

        try:
            camera = get_camera()
            camera.disconnect()
        except RuntimeError:
            pass
        upload_scheduler.stop()

    app = FastAPI(title="Ripe Recognition API", lifespan=lifespan)

    # License Guard — added first so CORS (added second) becomes outermost.
    # Response path: Router → License → CORS, so 403 from License gets CORS headers.
    if _lic_manager:
        app.add_middleware(LicenseGuardMiddleware, manager=_lic_manager)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static files — path /captures/... → artifacts/ directory
    # image_url format: "captures/results/{date}/{timestamp}.webp"
    artifacts_dir = settings.artifacts_dir
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/captures", StaticFiles(directory=str(artifacts_dir)), name="captures")

    app.include_router(health_router)
    app.include_router(inspection_router)
    app.include_router(streaming_router)
    app.include_router(capture_router)
    app.include_router(truck_router)
    app.include_router(internal_router)

    @app.websocket("/ws/results")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        state = get_runtime_state()
        state.websocket_clients.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            state.websocket_clients.remove(websocket)

    return app


app = create_app()
