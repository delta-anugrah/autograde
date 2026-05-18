from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ..core.config import Settings
from ..core.constants import (
    COLOR_FAIL,
    COLOR_PASS,
    FONT,
    FONT_COLOR,
)
from .model_registry import ModelRegistry


class RealtimeInspectionPipeline:
    def __init__(self, model_registry: ModelRegistry, settings: Settings) -> None:
        self.model_registry = model_registry
        self.settings = settings

    @property
    def model(self):
        return self.model_registry.model

    # ------------------------------------------------------------------ draw

    def draw_boxes(self, frame: np.ndarray, results: Any, classified_labels: dict) -> np.ndarray:
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            cls_id = int(box.cls[0])
            label = results.names[cls_id]
            score = float(box.conf[0])

            track_id = int(box.id[0]) if box.id is not None else None
            if track_id in classified_labels:
                label, score = classified_labels[track_id]

            color = COLOR_FAIL if "rej" in label.lower() else COLOR_PASS
            text = f"ID:{track_id} {label} ({score:.2f})"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, self.settings.border_thickness)
            (tw, th), _ = cv2.getTextSize(text, FONT, self.settings.font_scale, self.settings.font_thickness)
            cv2.rectangle(frame, (x1, y1 - th - 5), (x1 + tw, y1), color, -1)
            cv2.putText(frame, text, (x1, y1 - 5), FONT, self.settings.font_scale, FONT_COLOR, self.settings.font_thickness)
        return frame

    def draw_roi(self, frame: np.ndarray) -> np.ndarray:
        return frame

    # ----------------------------------------------------------------- track

    def track_ripeness(self, frame: np.ndarray) -> Any:
        return self.model.track(
            frame, persist=True, conf=self.settings.conf_threshold, tracker="bytetrack.yaml", verbose=False
        )[0]

    def get_status(self) -> dict:
        return {
            "device": self.model_registry.device,
            "model": str(self.settings.ripeness_model_path),
        }
