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
)
from .model_registry import ModelRegistry


class RealtimeInspectionPipeline:
    def __init__(self, model_registry: ModelRegistry, settings: Settings) -> None:
        self.model_registry = model_registry
        self.settings = settings
        self._roi_enabled = not (
            settings.roi_x1 == 0 and settings.roi_y1 == 0
            and settings.roi_x2 == 0 and settings.roi_y2 == 0
        )
        self._use_half = model_registry.device == "cuda"

    @property
    def model(self):
        return self.model_registry.model

    # ------------------------------------------------------------------ draw

    def draw_boxes(self, frame: np.ndarray, results: Any) -> np.ndarray:
        if results.boxes is None:
            return frame
        bt = self.settings.border_thickness
        fs = self.settings.font_scale
        ft = self.settings.font_thickness
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            label = results.names[int(box.cls[0].item())]
            score = float(box.conf[0].item())
            color = COLOR_FAIL if "rej" in label.lower() else COLOR_PASS
            # bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, bt)
            # label: teks berwarna saja (tanpa bar) — ACC hijau, REJ merah; outline hitam biar kebaca
            text = f"{label.upper()} {score * 100:.0f}%"
            (tw, th), bl = cv2.getTextSize(text, FONT, fs, ft)
            ty = y1 - 10 if y1 - th - 10 >= 0 else y1 + th + 10
            cv2.putText(frame, text, (x1, ty), FONT, fs, (0, 0, 0), ft + 4, cv2.LINE_AA)  # outline tebal
            cv2.putText(frame, text, (x1, ty), FONT, fs, color, ft + 1, cv2.LINE_AA)      # teks warna, agak tebal
        return frame

    def draw_roi(self, frame: np.ndarray) -> np.ndarray:
        if not self._roi_enabled:
            return frame
        h, w = frame.shape[:2]
        rx1 = self.settings.roi_x1
        ry1 = self.settings.roi_y1
        rx2 = self.settings.roi_x2 if self.settings.roi_x2 > 0 else w
        ry2 = self.settings.roi_y2 if self.settings.roi_y2 > 0 else h
        if rx2 <= rx1 or ry2 <= ry1:
            return frame
        cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), COLOR_ROI, 2)
        return frame

    # ----------------------------------------------------------------- track

    def track_ripeness(self, frame: np.ndarray) -> Any:
        return self.model.track(
            frame, persist=True, conf=self.settings.conf_threshold,
            tracker="bytetrack.yaml", verbose=False, half=self._use_half,
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
