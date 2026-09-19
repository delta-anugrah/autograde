from __future__ import annotations

from functools import lru_cache

from ..integrations.camera.base import CameraSource
from ..integrations.notifications.webhook_client import WebhookClient
from ..integrations.outbox.outbox_store import OutboxStore
from ..integrations.storage.local_file_storage import LocalFileStorage
from ..pipelines.model_registry import ModelRegistry
from ..pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline
from ..repositories.capture_repository import CaptureRepository
from ..repositories.result_repository import ResultRepository
from ..repositories.truck_repository import TruckRepository
from ..services.capture_service import CaptureService
from ..services.health_service import HealthService
from ..services.inspection_service import InspectionService
from ..services.result_service import ResultService
from ..services.streaming_service import StreamingService
from ..workers.runtime_state import RuntimeState
from .config import Settings

# Camera instance — diset oleh main.py saat startup
_camera: CameraSource | None = None


def set_camera(camera: CameraSource) -> None:
    global _camera
    _camera = camera


def get_camera() -> CameraSource:
    if _camera is None:
        raise RuntimeError("Camera belum diinisialisasi. Pastikan startup event sudah dijalankan.")
    return _camera


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_runtime_state() -> RuntimeState:
    return RuntimeState()


@lru_cache
def get_local_file_storage() -> LocalFileStorage:
    return LocalFileStorage()


@lru_cache
def get_webhook_client() -> WebhookClient:
    return WebhookClient(settings=get_settings())


@lru_cache
def get_model_registry() -> ModelRegistry:
    return ModelRegistry(settings=get_settings())


@lru_cache
def get_realtime_inspection_pipeline() -> RealtimeInspectionPipeline:
    return RealtimeInspectionPipeline(
        model_registry=get_model_registry(),
        settings=get_settings(),
    )


@lru_cache
def get_result_repository() -> ResultRepository:
    return ResultRepository(
        settings=get_settings(),
        storage=get_local_file_storage(),
    )


@lru_cache
def get_capture_repository() -> CaptureRepository:
    return CaptureRepository(
        settings=get_settings(),
        storage=get_local_file_storage(),
    )


@lru_cache
def get_truck_repository() -> TruckRepository:
    return TruckRepository(state=get_runtime_state())


def get_health_service() -> HealthService:
    return HealthService(
        settings=get_settings(),
        state=get_runtime_state(),
        camera=get_camera(),
        outbox=get_outbox_store(),
    )


@lru_cache
def get_inspection_service() -> InspectionService:
    return InspectionService(pipeline=get_realtime_inspection_pipeline())


@lru_cache
def get_streaming_service() -> StreamingService:
    return StreamingService(state=get_runtime_state())


@lru_cache
def get_outbox_store() -> OutboxStore:
    settings = get_settings()
    return OutboxStore(db_path=settings.artifacts_dir / "outbox.db")


def get_capture_service() -> CaptureService:
    return CaptureService(
        capture_repository=get_capture_repository(),
        truck_repository=get_truck_repository(),
        camera=get_camera(),
        state=get_runtime_state(),
        webhook=get_webhook_client(),
        settings=get_settings(),
        outbox_store=get_outbox_store(),
    )


@lru_cache
def get_result_service() -> ResultService:
    return ResultService(result_repository=get_result_repository())
