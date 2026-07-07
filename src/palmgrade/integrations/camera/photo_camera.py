from __future__ import annotations

import logging
from pathlib import Path

import cv2

from .base import CameraSource

logger = logging.getLogger(__name__)


class PhotoCamera(CameraSource):
    """Camera source dari single image file — frame yang sama dikembalikan terus."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._frame = None
        self.connected: bool = False

    def connect(self, index: int = 0, serial: str | None = None, feature_file: str | None = None) -> None:
        # serial & feature_file hanya relevan untuk kamera Hikrobot (GigE); diabaikan di sini.
        if not self.path.exists():
            raise RuntimeError(f"File tidak ditemukan: {self.path}")
        frame = cv2.imread(str(self.path))
        if frame is None:
            raise RuntimeError(f"Tidak bisa baca image: {self.path}")
        self._frame = frame
        self.connected = True
        logger.info("PhotoCamera loaded: %s", self.path)

    def grab_frame(self):
        return self._frame

    def disconnect(self) -> None:
        self._frame = None
        self.connected = False
        logger.info("PhotoCamera disconnected")
