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
        d = self.settings.conveyor_direction
        entry_off = self.settings.detection_entry_offset
        exit_off = self.settings.detection_exit_offset
        roi_color = np.array(COLOR_ROI, dtype=np.float32)

        if d in ("rtl", "ltr"):
            entry_x = max(0, w - entry_off) if d == "rtl" else min(w, entry_off)
            exit_x = min(w, exit_off) if d == "rtl" else max(0, w - exit_off)
            x1, x2 = min(entry_x, exit_x), max(entry_x, exit_x)
            if x2 > x1:
                region = frame[:, x1:x2]
                frame[:, x1:x2] = (region * (1.0 - ROI_ALPHA) + roi_color * ROI_ALPHA).astype(np.uint8)
        else:  # ttb, btt
            entry_y = min(h, entry_off) if d == "ttb" else max(0, h - entry_off)
            exit_y = max(0, h - exit_off) if d == "ttb" else min(h, exit_off)
            y1, y2 = min(entry_y, exit_y), max(entry_y, exit_y)
            if y2 > y1:
                region = frame[y1:y2, :]
                frame[y1:y2, :] = (region * (1.0 - ROI_ALPHA) + roi_color * ROI_ALPHA).astype(np.uint8)

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
