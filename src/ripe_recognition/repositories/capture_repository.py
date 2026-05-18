from __future__ import annotations

import datetime
from typing import Any

import numpy as np

from ..core.config import Settings
from ..core.constants import (
    JPEG_QUALITY_SAVE,
    MANUAL_CAPTURE_CONFIDENCE,
    MANUAL_CAPTURE_STATUS,
    MANUAL_CAPTURE_SUFFIX,
)
from ..integrations.storage.local_file_storage import LocalFileStorage


class CaptureRepository:
    def __init__(self, settings: Settings, storage: LocalFileStorage) -> None:
        self.settings = settings
        self.storage = storage

    def save_manual_reject(
        self,
        frame: np.ndarray,
        truck_id: str | None,
    ) -> dict[str, Any]:
        now = datetime.datetime.now()
        date_folder = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y-%m-%d_%H%M%S_%f")

        results_dir = self.settings.results_dir / date_folder
        img_filename = f"{timestamp}_{MANUAL_CAPTURE_SUFFIX}.jpg"
        image_url = f"captures/results/{date_folder}/{img_filename}"

        height, width = frame.shape[:2]
        bounding_box = {"x_min": 0, "y_min": 0, "x_max": width, "y_max": height}

        payload: dict[str, Any] = {
            "id": timestamp,
            "ripeness_status": MANUAL_CAPTURE_STATUS,
            "ripeness_confidence": MANUAL_CAPTURE_CONFIDENCE,
            "tp_status": None,
            "tp_confidence": 0,
            "title": "FAIL Detected (Manual)",
            "description": f"Manual reject capture (truck_id={truck_id})",
            "timestamp": now.isoformat(),
            "image_url": image_url,
            "capture_type": MANUAL_CAPTURE_SUFFIX,
            "truck_id": truck_id,
            "bounding_box": bounding_box,
        }

        self.storage.write_image(results_dir / img_filename, frame, quality=JPEG_QUALITY_SAVE)
        self.storage.write_json(results_dir / f"{timestamp}_{MANUAL_CAPTURE_SUFFIX}.json", payload)

        # Duplikasi ke errors/ karena manual capture selalu FAIL
        errors_dir = self.settings.errors_dir / date_folder
        self.storage.write_image(errors_dir / img_filename, frame, quality=JPEG_QUALITY_SAVE)
        self.storage.write_json(errors_dir / f"{timestamp}_{MANUAL_CAPTURE_SUFFIX}.json", payload)

        return payload
