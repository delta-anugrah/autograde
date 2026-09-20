from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from ..core.config import Settings
from ..core.constants import (
    MANUAL_CAPTURE_CONFIDENCE,
    MANUAL_CAPTURE_STATUS,
    MANUAL_CAPTURE_SUFFIX,
)
from ..services.capture_writer import CaptureWriter

if TYPE_CHECKING:  # annotations only — numpy and cv2 are absent from the unit
    # suite on purpose (CLAUDE.md § Tests). The frame is passed in and storage is
    # injected, so nothing in this module ever constructs either.
    import numpy as np

    from ..integrations.storage.local_file_storage import LocalFileStorage


class CaptureRepository:
    def __init__(self, settings: Settings, storage: LocalFileStorage) -> None:
        self.settings = settings
        self.storage = storage
        self.writer = CaptureWriter(settings, storage)

    def save_manual_reject(
        self,
        frame: np.ndarray,
        truck_id: str | None,
        assignment_id: str | None = None,
        plate: str | None = None,
        assigned_at: str | None = None,
    ) -> dict[str, Any]:
        # Aware UTC so the filename shares one instant with the payload
        # timestamp below (which was already UTC-aware).
        now = datetime.datetime.now(datetime.timezone.utc)
        date_folder = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y-%m-%d_%H%M%S_%f")

        results_dir = self.settings.results_dir / date_folder
        img_filename = f"{timestamp}_{MANUAL_CAPTURE_SUFFIX}.webp"

        # Same layout as the auto path — one writer for both, or the folders
        # come to mean different things depending on who filled them.
        truck_folder = self.writer.truck_folder(
            assignment_id=assignment_id, plate=plate, assigned_at=assigned_at, now=now
        )
        # A manual reject is never drawn on, so both copies are the same frame.
        # Written anyway: `bbox/` is where every consumer looks for the image a
        # record points at, and `clean/` is where a training run collects them —
        # a gap in either would have to be special-cased by both.
        # No class: a manual reject never went through the model, so it lands in
        # `unknown/` rather than borrowing a class it was never given. TP is not
        # looked for either, for the same reason.
        image_url = self.writer.write_pair(
            date_folder=date_folder,
            truck_folder=truck_folder,
            grade_class=None,
            filename=img_filename,
            annotated_frame=frame,
            clean_frame=frame,
        )

        height, width = frame.shape[:2]
        bounding_box = {"x_min": 0, "y_min": 0, "x_max": width, "y_max": height}

        payload: dict[str, Any] = {
            "id": timestamp,
            "ripeness_status": MANUAL_CAPTURE_STATUS,
            "ripeness_confidence": MANUAL_CAPTURE_CONFIDENCE,
            # Same three TP fields as the auto sidecar, always present and empty
            # here: one shape for every reader (`capture_save_worker.run_once`).
            "tp_status": False,
            "tp_confidence": 0,
            "tp_bounding_box": None,
            "title": "FAIL Detected (Manual)",
            "description": f"Manual reject capture (truck_id={truck_id})",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "image_url": image_url,
            "capture_type": MANUAL_CAPTURE_SUFFIX,
            "truck_id": truck_id,
            "bounding_box": bounding_box,
            "assignment_id": assignment_id,
        }

        json_filename = f"{timestamp}_{MANUAL_CAPTURE_SUFFIX}_ripeness.json"
        self.storage.write_json(results_dir / json_filename, payload)

        # results/ adalah satu-satunya sumber kebenaran; status FAIL ada di metadata
        # (ripeness_status), jadi tidak perlu salinan terpisah di errors/.
        return payload
