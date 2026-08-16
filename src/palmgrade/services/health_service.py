from __future__ import annotations

from dataclasses import dataclass

import torch

from ..core.config import Settings
from ..integrations.camera.base import CameraSource
from ..integrations.outbox.outbox_store import OutboxStore
from ..plc import diagnostics as plc_diagnostics
from ..schemas.common_schema import HealthDetailSchema, WorkerStatus
from ..workers.runtime_state import RuntimeState


@dataclass
class HealthService:
    settings: Settings
    state: RuntimeState
    camera: CameraSource
    outbox: OutboxStore

    def get_health(self) -> dict[str, str]:
        return {
            "message": "Ripe Recognition API is ready.",
            "detail": f"Environment: {self.settings.environment}",
        }

    def get_health_detail(self) -> HealthDetailSchema:
        gpu_available = torch.cuda.is_available()
        gpu_device = torch.cuda.get_device_name(0) if gpu_available else None

        workers = [
            WorkerStatus(name=name, alive=thread.is_alive())
            for name, thread, _ in self.state.worker_threads
        ]

        return HealthDetailSchema(
            status="ok",
            environment=self.settings.environment,
            camera_type=self.settings.camera_type,
            camera_connected=self.camera.connected,
            plc=plc_diagnostics(),
            gpu_available=gpu_available,
            gpu_device=gpu_device,
            machine_id=self.settings.machine_id,
            workers=workers,
            outbox_pending=self.outbox.pending_count(),
            outbox_failed=self.outbox.failed_count(),
            current_assignment_id=self.state.current_assignment_id,
            last_successful_api_push=self.state.last_successful_api_push,
        )
