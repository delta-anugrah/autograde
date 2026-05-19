from __future__ import annotations

import logging

import cv2

from .base import CameraSource

logger = logging.getLogger(__name__)


class OpenCVCamera(CameraSource):
    """Fallback camera untuk development tanpa hardware Hikrobot."""

    def __init__(self, source: int | str = 0, width: int = 0, height: int = 0, fps: int = 0) -> None:
        self.source = source
        self.width = width
        self.height = height
        self.fps = fps
        self._cap: cv2.VideoCapture | None = None
        self.connected: bool = False

    def connect(self, index: int = 0) -> None:
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Tidak bisa buka camera source: {self.source}")
        if self.width:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.fps:
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.connected = True
        logger.info("OpenCV camera connected: %s", self.source)

    def grab_frame(self):
        if self._cap is None or not self._cap.isOpened():
            return None
        ret, frame = self._cap.read()
        if not ret:
            # Video ended — rewind and try once more (loop for testing)
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
        return frame if ret else None

    def disconnect(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None
            self.connected = False
            logger.info("OpenCV camera disconnected")
