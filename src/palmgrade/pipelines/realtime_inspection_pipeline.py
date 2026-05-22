from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ..core.config import Settings
from ..core.constants import (
    COLOR_FAIL,
    COLOR_PASS,
    COLOR_ROI,
    FONT,
    FONT_COLOR,
    ROI_ALPHA,
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

    def draw_boxes(self, frame: np.ndarray, results: Any) -> np.ndarray:
        if results.boxes is None:
            return frame
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            cls_id = int(box.cls[0])
            label = results.names[cls_id]
            score = float(box.conf[0])
            track_id = int(box.id[0]) if box.id is not None else None
            color = COLOR_FAIL if "rej" in label.lower() else COLOR_PASS
            text = f"ID:{track_id} {label} ({score:.2f})"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, self.settings.border_thickness)
            (tw, th), _ = cv2.getTextSize(text, FONT, self.settings.font_scale, self.settings.font_thickness)
            cv2.rectangle(frame, (x1, y1 - th - 5), (x1 + tw, y1), color, -1)
            cv2.putText(frame, text, (x1, y1 - 5), FONT, self.settings.font_scale, FONT_COLOR, self.settings.font_thickness)
        return frame

    def draw_roi(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        rx1 = self.settings.roi_x1
        ry1 = self.settings.roi_y1
        rx2 = self.settings.roi_x2 if self.settings.roi_x2 > 0 else w
        ry2 = self.settings.roi_y2 if self.settings.roi_y2 > 0 else h
        if rx2 <= rx1 or ry2 <= ry1:
            return frame
        roi_color = np.array(COLOR_ROI, dtype=np.float32)
        region = frame[ry1:ry2, rx1:rx2]
        frame[ry1:ry2, rx1:rx2] = (region * (1.0 - ROI_ALPHA) + roi_color * ROI_ALPHA).astype(np.uint8)
        cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), COLOR_ROI, 2)
        return frame

    # ----------------------------------------------------------------- track

    def track_ripeness(self, frame: np.ndarray) -> Any:
        return self.model.track(
            frame, persist=True, conf=self.settings.conf_threshold, tracker="bytetrack.yaml", verbose=False
        )[0]

    def reset_tracker(self) -> None:
        try:
            if self.model.predictor is not None and hasattr(self.model.predictor, "trackers"):
                for tracker in self.model.predictor.trackers:
                    tracker.reset()
        except Exception:
            pass

    def get_status(self) -> dict:
        return {
            "device": self.model_registry.device,
            "model": str(self.settings.ripeness_model_path),
        }
