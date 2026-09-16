from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ..core.config import Settings
from ..core.constants import (
    COLOR_FAIL,
    COLOR_PASS,
    COLOR_ROI,
    COLOR_TP,
    FONT,
    FONT_COLOR,
)
from ..domain.grade_class import TP, grade_class_or_none, verdict_for_class
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
            # Warna ikut VERDICT, bukan substring nama kelas. Dulu barisnya
            # `"rej" in label.lower()`, dan itu benar selama model masih
            # ACC/Rej/TP. Untuk model 4 kelas SALAH TOTAL: `Unripe` dan `JK`
            # tidak mengandung "rej", jadi janjang yang justru dibuang piston
            # digambar HIJAU — operator melihat hijau untuk buah yang ditolak.
            kelas = grade_class_or_none(label)
            verdict = verdict_for_class(kelas) if kelas else None
            color = COLOR_FAIL if verdict == "REJ" else COLOR_PASS
            # TP bukan buah dan tidak punya verdict: dikuningkan supaya tidak
            # terbaca sebagai "lolos" padahal dia cuma penanda tangkai panjang.
            if kelas == TP:
                color = COLOR_TP
            # bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, bt)
            # Teks memakai nama kelas apa adanya (Ripe/Unripe/JK/TP), BUKAN
            # `.upper()`: operator menyebut kelasnya persis begini, dan JK yang
            # jadi "JK" sama saja sedangkan "UNRIPE" lebih sulit dipindai mata
            # dari jarak jauh daripada "Unripe".
            text = f"{kelas or label} {score * 100:.0f}%"
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

    def track_ripeness(self, frame: np.ndarray, conf: float | None = None) -> Any:
        """`conf` menimpa `CONF_THRESHOLD` dari `.env` kalau diisi.

        Dikirim sebagai argumen, bukan dibaca dari `RuntimeState` di sini:
        pipeline sengaja tidak tahu apa-apa soal state runtime — yang memegang
        state itu worker, dan itu yang membuat pipeline bisa dites tanpa merakit
        satu line pun.
        """
        return self.model.track(
            frame, persist=True,
            conf=self.settings.conf_threshold if conf is None else conf,
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
