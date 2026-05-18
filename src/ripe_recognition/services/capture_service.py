from __future__ import annotations

import asyncio
from typing import Any

from ..integrations.camera.base import CameraSource
from ..integrations.notifications.webhook_client import WebhookClient
from ..repositories.capture_repository import CaptureRepository
from ..repositories.truck_repository import TruckRepository
from ..workers.runtime_state import RuntimeState


class CaptureService:
    def __init__(
        self,
        capture_repository: CaptureRepository,
        truck_repository: TruckRepository,
        camera: CameraSource,
        state: RuntimeState,
        webhook: WebhookClient,
    ) -> None:
        self.capture_repository = capture_repository
        self.truck_repository = truck_repository
        self.camera = camera
        self.state = state
        self.webhook = webhook

    def capture_manual_reject(self) -> dict[str, Any]:
        with self.state.lock:
            frame = self.camera.grab_frame()

        if frame is None:
            raise RuntimeError("Failed to capture frame from camera")

        truck_id = self.truck_repository.get_current_truck_id()

        result = self.capture_repository.save_manual_reject(
            frame=frame,
            truck_id=truck_id,
        )

        self.state.event_queue.put({
            "id": result["id"],
            "ripeness_status": result["ripeness_status"],
            "ripeness_confidence": result["ripeness_confidence"],
            "tp_status": result.get("tp_status"),
            "tp_score": result.get("tp_confidence", 0),
            "title": result["title"],
            "description": result["description"],
            "timestamp": result["timestamp"],
            "image_url": result["image_url"],
            "capture_type": result["capture_type"],
            "truck_id": result["truck_id"],
        })

        webhook_payload = {
            "timestamp": result["timestamp"],
            "image_path": result["image_url"],
            "ripeness_status": result["ripeness_status"],
            "ripeness_confidence": result["ripeness_confidence"],
            "tp_status": None,
            "tp_confidence": 0,
            "capture_type": result["capture_type"],
            "truck_id": truck_id,
            "bounding_box": result["bounding_box"],
        }
        if self.state.main_loop:
            asyncio.run_coroutine_threadsafe(
                self.webhook.send_quality_event(webhook_payload),
                self.state.main_loop,
            )

        return result
