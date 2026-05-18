from __future__ import annotations

import cv2

from .base import CameraSource


class OpenCVCamera(CameraSource):
    """Fallback camera untuk development tanpa hardware Hikrobot."""

    def __init__(self, source: int | str = 0) -> None:
        self.source = source
        self._cap: cv2.VideoCapture | None = None

    def connect(self, index: int = 0) -> None:
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Tidak bisa buka camera source: {self.source}")
        print(f"[INFO] OpenCV camera connected: {self.source}")

    def grab_frame(self):
        if self._cap is None or not self._cap.isOpened():
            return None
        ret, frame = self._cap.read()
        return frame if ret else None

    def disconnect(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None
            print("[INFO] OpenCV camera disconnected")
