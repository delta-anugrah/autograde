from __future__ import annotations

import logging

import cv2

from .base import CameraSource

logger = logging.getLogger(__name__)


class OpenCVCamera(CameraSource):
    """Fallback camera untuk development tanpa hardware Hikrobot."""

    def __init__(
        self,
        source: int | str = 0,
        width: int = 0,
        height: int = 0,
        fps: int = 0,
        is_video_file: bool = False,
    ) -> None:
        self.source = source
        self.width = width
        self.height = height
        self.fps = fps
        self._is_video_file = is_video_file
        self._cap: cv2.VideoCapture | None = None
        self.connected: bool = False
        self._rewound: bool = False
        self._exhausted: bool = False

    def connect(self, index: int = 0, serial: str | None = None) -> None:
        # serial hanya relevan untuk kamera Hikrobot (GigE); diabaikan di sini.
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Tidak bisa buka camera source: {self.source}")
        if self.width:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if self.fps:
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        else:
            detected = self._cap.get(cv2.CAP_PROP_FPS)
            if detected and detected > 0:
                self.fps = detected
                logger.info("OpenCV camera: auto-detected FPS=%.2f", self.fps)
        self.connected = True
        self._exhausted = False
        logger.info("OpenCV camera connected: %s", self.source)

    def get_fps(self) -> float:
        return float(self.fps)

    @property
    def rewound(self) -> bool:
        return self._rewound

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    @property
    def supports_reconnect(self) -> bool:
        return not self._is_video_file

    def grab_frame(self):
        if self._cap is None or not self._cap.isOpened():
            return None
        if self._exhausted:
            return None
        self._rewound = False
        ret, frame = self._cap.read()
        if not ret:
            if self._is_video_file:
                self._exhausted = True
                self.disconnect()
                logger.info("OpenCV video finished once and stopped: %s", self.source)
                return None
            return None
        return frame

    def disconnect(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None
            self.connected = False
            logger.info("OpenCV camera disconnected")
