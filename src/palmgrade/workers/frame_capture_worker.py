from __future__ import annotations

import logging
import queue
import time

from ..integrations.camera.base import CameraSource
from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILURES = 5
_RECONNECT_BACKOFF_BASE = 1.0
_RECONNECT_BACKOFF_MAX = 30.0


class FrameCaptureWorker:
    def __init__(self, camera: CameraSource, state: RuntimeState, target_fps: int = 24, **_) -> None:
        self.camera = camera
        self.state = state
        self._frame_interval = 1.0 / max(1, target_fps)
        self._last_frame_time: float = 0.0
        self._consecutive_failures: int = 0
        self._reconnect_backoff: float = _RECONNECT_BACKOFF_BASE

    def _try_reconnect(self) -> None:
        logger.warning("Camera: %d consecutive failures — attempting reconnect", self._consecutive_failures)
        try:
            self.camera.disconnect()
        except Exception:
            pass
        time.sleep(self._reconnect_backoff)
        self._reconnect_backoff = min(self._reconnect_backoff * 2, _RECONNECT_BACKOFF_MAX)
        try:
            self.camera.connect()
            self._consecutive_failures = 0
            self._reconnect_backoff = _RECONNECT_BACKOFF_BASE
            logger.info("Camera reconnected successfully")
        except Exception as exc:
            logger.error("Camera reconnect failed: %s", exc)

    def run_once(self) -> None:
        now = time.time()
        wait = self._frame_interval - (now - self._last_frame_time)
        if wait > 0:
            time.sleep(wait)
        self._last_frame_time = time.time()

        with self.state.lock:
            frame = self.camera.grab_frame()

        if frame is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                self._try_reconnect()
            else:
                time.sleep(0.01)
            return

        self._consecutive_failures = 0
        self._reconnect_backoff = _RECONNECT_BACKOFF_BASE
        self.state.latest_raw_frame = frame

        try:
            self.state.frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    def run_loop(self) -> None:
        while True:
            self.run_once()
