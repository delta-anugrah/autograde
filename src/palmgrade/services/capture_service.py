from __future__ import annotations

import logging
import queue
from typing import Any

from ..core.config import Settings
from ..domain.vision_event import build_event_payload
from ..integrations.camera.base import CameraSource
from ..integrations.notifications.webhook_client import WebhookClient
from ..integrations.outbox.outbox_store import OutboxStore
from ..repositories.capture_repository import CaptureRepository
from ..repositories.truck_repository import TruckRepository
from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class CaptureService:
    def __init__(
        self,
        capture_repository: CaptureRepository,
        truck_repository: TruckRepository,
        camera: CameraSource,
        state: RuntimeState,
        webhook: WebhookClient,
        settings: Settings,
        outbox_store: OutboxStore,
    ) -> None:
        self.capture_repository = capture_repository
        self.truck_repository = truck_repository
        self.camera = camera
        self.state = state
        self.webhook = webhook
        self.settings = settings
        self.outbox_store = outbox_store

    def capture_manual_reject(self) -> dict[str, Any]:
        with self.state.lock:
            frame = self.camera.grab_frame()

        if frame is None:
            raise RuntimeError("Failed to capture frame from camera")

        truck_id = self.truck_repository.get_current_truck_id()

        result = self.capture_repository.save_manual_reject(
            frame=frame,
            truck_id=truck_id,
            assignment_id=self.state.current_assignment_id,
        )

        event = {
            "id": result["id"],
            "ripeness_status": result["ripeness_status"],
            "ripeness_confidence": result["ripeness_confidence"],
            "tp_status": result.get("tp_status"),
            "tp_confidence": result.get("tp_confidence", 0),
            "title": result["title"],
            "description": result["description"],
            "timestamp": result["timestamp"],
            "image_url": result["image_url"],
            "capture_type": result["capture_type"],
            "truck_id": result["truck_id"],
            "machine_id": self.settings.machine_id,
        }
        # H2: drop-old pattern — never block on a slow WebSocket client
        try:
            self.state.event_queue.get_nowait()
        except queue.Empty:
            pass
        self.state.event_queue.put_nowait(event)

        # Realtime ke API lokal: OutboxRetryWorker mengirim ini dalam ~1 detik,
        # jadi operator lihat hasilnya di Grading History tanpa nunggu batch R2.
        outbox_payload = build_event_payload(
            machine_id=self.settings.machine_id,
            file_ts=result["id"],
            timestamp=result["timestamp"],
            ripeness_status=result["ripeness_status"],
            ripeness_confidence=result["ripeness_confidence"],
            capture_type=result["capture_type"],
            image_path=result.get("image_url", ""),
            truck_id=truck_id,
            assignment_id=self.state.current_assignment_id,
            bounding_box=result.get("bounding_box"),
        )
        try:
            self.outbox_store.add_event(
                outbox_payload["event_id"], self.settings.machine_id, outbox_payload
            )
        except Exception as exc:
            # Gambar sudah aman di disk dan batch R2 masih bisa menyusul —
            # menggagalkan request di sini bikin tombol capture balas 500
            # padahal capture-nya sendiri sukses.
            logger.error("Failed to write event %s to outbox: %s", outbox_payload["event_id"], exc)

        return result
