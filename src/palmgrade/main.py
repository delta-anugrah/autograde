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
    get_realtime_inspection_pipeline,
    get_runtime_state,
    get_settings,
    get_webhook_client,
    set_camera,
)
from .core.logging import configure_logging
from .integrations.camera.base import CameraSource
from .integrations.camera.hikrobot_camera import HikrobotCamera
from .integrations.camera.opencv_camera import OpenCVCamera
from .integrations.camera.photo_camera import PhotoCamera
from .license.guard import LicenseGuardMiddleware
from .license.local_repo import LicenseLocalRepo
from .license.manager import LicenseManager
from .license.sync_client import SyncClient
from .integrations.scheduler.upload_scheduler import UploadScheduler
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

        if settings.webhook_secret == "supersecret123":
            logger.warning("WEBHOOK_SECRET is using the default value — set it before production deployment")

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
            )
        elif camera_type == "photo":
            camera = PhotoCamera(path=settings.camera_photo_path)
        else:
            camera = HikrobotCamera()

        camera.connect(index=settings.camera_device_index)
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

        capture_worker = FrameCaptureWorker(camera=camera, state=state, target_fps=settings.camera_fps)
        display_worker = DisplayWorker(state=state, pipeline=pipeline, settings=settings, target_fps=settings.camera_fps)
        processing_worker = FrameProcessingWorker(
            pipeline=pipeline,
            state=state,
            storage=storage_instance,
            webhook=webhook,
            settings=settings,
        )

        state.worker_threads = [
            ("capture", _start_worker("capture", capture_worker.run_loop), capture_worker),
            ("display", _start_worker("display", display_worker.run_loop), display_worker),
            ("processing", _start_worker("processing", processing_worker.run_loop), processing_worker),
        ]

        async def _watchdog() -> None:
            while True:
                await asyncio.sleep(10)
                for i, (name, thread, worker) in enumerate(state.worker_threads):
                    if not thread.is_alive():
                        logger.error("Worker thread '%s' died — restarting", name)
                        new_thread = _start_worker(name, worker.run_loop)
                        state.worker_threads[i] = (name, new_thread, worker)

        asyncio.create_task(_watchdog())

        upload_scheduler = UploadScheduler(settings=settings)
        upload_scheduler.start()

        yield

        from .core.dependencies import get_camera
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
    # image_url format: "captures/results/{date}/{timestamp}.jpg"
    artifacts_dir = settings.artifacts_dir
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/captures", StaticFiles(directory=str(artifacts_dir)), name="captures")

    app.include_router(health_router)
    app.include_router(inspection_router)
    app.include_router(streaming_router)
    app.include_router(capture_router)
    app.include_router(truck_router)

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
