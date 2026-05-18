from __future__ import annotations

from pathlib import Path

import cv2

from .base import CameraSource


class PhotoCamera(CameraSource):
    """Camera source dari single image file — frame yang sama dikembalikan terus."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._frame = None

    def connect(self, index: int = 0) -> None:
        if not self.path.exists():
            raise RuntimeError(f"File tidak ditemukan: {self.path}")
        frame = cv2.imread(str(self.path))
        if frame is None:
            raise RuntimeError(f"Tidak bisa baca image: {self.path}")
        self._frame = frame
        print(f"[INFO] PhotoCamera loaded: {self.path}")

    def grab_frame(self):
        return self._frame

    def disconnect(self) -> None:
        self._frame = None
        print("[INFO] PhotoCamera disconnected")
