from __future__ import annotations

import asyncio
import threading

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.dependencies import (
    get_capture_repository,
    get_model_registry,
    get_realtime_inspection_pipeline,
    get_runtime_state,
    get_settings,
    get_webhook_client,
    set_camera,
)
from .core.logging import configure_logging
from .integrations.camera.hikrobot_camera import HikrobotCamera
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
from .workers.event_broadcast_worker import EventBroadcastWorker
from .workers.frame_capture_worker import FrameCaptureWorker
from .workers.frame_processing_worker import FrameProcessingWorker

load_dotenv()

_upload_scheduler: UploadScheduler | None = None


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(title="Ripe Recognition API")

    # License Guard — wired before CORS so it runs outermost
    _lic_manager: LicenseManager | None = None
    if settings.lic_enabled:
        _lic_repo = LicenseLocalRepo(settings.artifacts_dir / "license.db")
        _lic_sync = SyncClient(settings.lic_server_url, settings.lic_api_key)
        _lic_manager = LicenseManager(settings.lic_pubkey_pem, _lic_repo, _lic_sync)
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

    @app.on_event("startup")
    async def startup_event() -> None:
        global _upload_scheduler

        if _lic_manager:
            await _lic_manager.init()

        # Buat folder artifacts yang diperlukan
        for folder in [settings.captures_dir, settings.results_dir, settings.errors_dir, settings.logs_dir]:
            folder.mkdir(parents=True, exist_ok=True)

        # Init kamera — pilih salah satu source di bawah, sisanya komen
        # [PRODUCTION] Hikrobot industrial camera (butuh SDK + hardware)
        camera = HikrobotCamera()

        # [DEVELOPMENT] Webcam (0 = default, ganti angka jika multi-cam)
        # from .integrations.camera.opencv_camera import OpenCVCamera
        # camera = OpenCVCamera(source=0)

        # [TESTING] Video file
        # from .integrations.camera.opencv_camera import OpenCVCamera
        # camera = OpenCVCamera(source="/path/to/video.mp4")

        # [TESTING] Single image / photo (frame yang sama dikembalikan terus)
        # from .integrations.camera.photo_camera import PhotoCamera
        # camera = PhotoCamera(path="/path/to/image.jpg")

        camera.connect(index=settings.camera_device_index)
        set_camera(camera)

        state = get_runtime_state()
        state.main_loop = asyncio.get_running_loop()

        pipeline = get_realtime_inspection_pipeline()
        storage_instance = get_capture_repository().storage
        webhook = get_webhook_client()

        # Start async broadcast task
        broadcast_worker = EventBroadcastWorker(state=state)
        asyncio.create_task(broadcast_worker.run_loop())

        # Start frame capture thread
        capture_worker = FrameCaptureWorker(camera=camera, state=state)
        threading.Thread(target=capture_worker.run_loop, daemon=True).start()

        # Start frame processing thread
        processing_worker = FrameProcessingWorker(
            pipeline=pipeline,
            state=state,
            storage=storage_instance,
            webhook=webhook,
            settings=settings,
        )
        threading.Thread(target=processing_worker.run_loop, daemon=True).start()

        # Start scheduler
        _upload_scheduler = UploadScheduler(settings=settings)
        _upload_scheduler.start()

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        from .core.dependencies import get_camera
        try:
            camera = get_camera()
            camera.disconnect()
        except RuntimeError:
            pass

        if _upload_scheduler:
            _upload_scheduler.stop()

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
