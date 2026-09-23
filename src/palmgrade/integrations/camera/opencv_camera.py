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
        loop: bool = False,
    ) -> None:
        self.source = source
        self.width = width
        self.height = height
        self.fps = fps
        self._is_video_file = is_video_file
        # Start over at the end instead of stopping (CAMERA_VIDEO_LOOP). Video only.
        self._loop = loop and is_video_file
        self._cap: cv2.VideoCapture | None = None
        self.connected: bool = False
        self._rewound: bool = False
        self._exhausted: bool = False

    def connect(self, index: int = 0, serial: str | None = None, feature_file: str | None = None) -> None:
        # serial & feature_file hanya relevan untuk kamera Hikrobot (GigE); diabaikan di sini.
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Tidak bisa buka camera source: {self.source}")
        if self.width:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        # Sebuah BERKAS punya lajunya sendiri, dan itu yang menang — selalu.
        # Menyetel `CAP_PROP_FPS` pada berkas tidak mengubah isinya; ia cuma
        # membuat `get_fps()` membalas angka yang dipaksakan, jadi laju asli
        # hilang tanpa jejak dan pemutaran ikut melambat. Terjadi di PC pabrik:
        # `CAMERA_FPS=20` membuat berkas 30 fps diputar 20 fps, dan rekamannya
        # ikut salah durasi.
        #
        # Untuk perangkat sungguhan (webcam) menyetelnya tetap bermakna — itu
        # perintah ke driver, bukan pembacaan.
        terbaca = self._cap.get(cv2.CAP_PROP_FPS)
        if self._is_video_file and terbaca and terbaca > 0:
            if self.fps and abs(float(self.fps) - terbaca) > 0.01:
                logger.info(
                    "Berkas video berjalan pada lajunya sendiri: %.2f fps "
                    "(CAMERA_FPS=%s diabaikan untuk berkas)",
                    terbaca, self.fps,
                )
            self.fps = terbaca
        elif self.fps:
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        elif terbaca and terbaca > 0:
            self.fps = terbaca
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
        if ret:
            return frame
        if not self._is_video_file:
            return None
        if self._loop:
            frame = self._start_over()
            if frame is not None:
                return frame
            logger.warning("OpenCV video cannot start over, stopping: %s", self.source)
        self._exhausted = True
        self.disconnect()
        logger.info("OpenCV video finished once and stopped: %s", self.source)
        return None

    def _start_over(self):
        """Seek back to frame 0 and read it. None if the file will not seek or is empty,
        so a broken clip stops instead of spinning on an endless read-fail-seek."""
        if not self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0):
            return None
        ret, frame = self._cap.read()
        if not ret:
            return None
        self._rewound = True  # tells the capture worker to reset tracking
        return frame

    def disconnect(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None
            self.connected = False
            logger.info("OpenCV camera disconnected")
