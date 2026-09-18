from __future__ import annotations

from dataclasses import dataclass

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
            "version": self.settings.app_version,
        }

    def get_health_detail(self) -> HealthDetailSchema:
        # torch di-import di sini, bukan di level modul: CI unit test sengaja
        # tidak memasang torch/opencv (lihat .github/workflows/ci.yml), dan
        # get_health() harus tetap bisa diuji tanpa itu.
        import torch

        gpu_available = torch.cuda.is_available()
        gpu_device = torch.cuda.get_device_name(0) if gpu_available else None

        workers = [
            WorkerStatus(name=name, alive=thread.is_alive())
            for name, thread, _ in self.state.worker_threads
        ]

        # Penulis bukti dicari lewat daftar worker, bukan disuntik sendiri:
        # `HealthService` dirakit `get_health_service()` yang tidak tahu apa-apa
        # soal worker, dan menambah satu dependensi lagi ke situ cuma untuk dua
        # angka tidak sepadan. Line konsol (`APP_MODE=console`) tidak punya
        # penulis sama sekali, jadi ketiadaannya normal, bukan kesalahan.
        saver = next(
            (w for name, _t, w in self.state.worker_threads if name == "capture_save"), None
        )

        return HealthDetailSchema(
            status="ok",
            environment=self.settings.environment,
            version=self.settings.app_version,
            camera_type=self.settings.camera_type,
            camera_connected=self.camera.connected,
            plc=plc_diagnostics(),
            gpu_available=gpu_available,
            gpu_device=gpu_device,
            machine_id=self.settings.machine_id,
            workers=workers,
            outbox_pending=self.outbox.pending_count(),
            outbox_failed=self.outbox.failed_count(),
            capture_save_pending=saver.antrean if saver else 0,
            capture_save_dropped=saver.dibuang if saver else 0,
            current_assignment_id=self.state.current_assignment_id,
            last_successful_api_push=self.state.last_successful_api_push,
        )
