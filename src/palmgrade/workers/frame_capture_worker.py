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
    def __init__(self, camera: CameraSource, state: RuntimeState, target_fps: int = 24, device_index: int = 0, **_) -> None:
        self.camera = camera
        self.state = state
        self._device_index = device_index
        self._target_fps = target_fps
        self._frame_interval = 1.0 / max(1, target_fps) if target_fps > 0 else 0.0
        self._last_frame_time: float = 0.0
        self._consecutive_failures: int = 0
        self._reconnect_backoff: float = _RECONNECT_BACKOFF_BASE
        self._fps_counter: int = 0
        self._fps_timer: float = 0.0
        self._exhausted_logged: bool = False

    def _sync_fps_from_camera(self) -> None:
        if self._target_fps == 0:
            detected = self.camera.get_fps()
            if detected > 0:
                self._frame_interval = 1.0 / detected
                logger.info("FrameCaptureWorker: using camera FPS=%.2f", detected)

    def _try_reconnect(self) -> None:
        logger.warning("Camera: %d consecutive failures — attempting reconnect", self._consecutive_failures)
        try:
            self.camera.disconnect()
        except Exception:
            pass
        time.sleep(self._reconnect_backoff)
        self._reconnect_backoff = min(self._reconnect_backoff * 2, _RECONNECT_BACKOFF_MAX)
        try:
            self.camera.connect(index=self._device_index)
            self._consecutive_failures = 0
            self._reconnect_backoff = _RECONNECT_BACKOFF_BASE
            self._sync_fps_from_camera()
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
            if self.camera.exhausted:
                if not self._exhausted_logged:
                    logger.info("Camera source exhausted — capture paused without reconnect")
                    self._exhausted_logged = True
                self._consecutive_failures = 0
                time.sleep(max(self._frame_interval, 0.25))
                return

            self._exhausted_logged = False
            self._consecutive_failures += 1
            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES and self.camera.supports_reconnect:
                self._try_reconnect()
            else:
                time.sleep(0.01)
            return

        self._exhausted_logged = False
        self._consecutive_failures = 0
        self._reconnect_backoff = _RECONNECT_BACKOFF_BASE
        self.state.latest_raw_frame = frame

        self._fps_counter += 1
        if self._fps_timer == 0.0:
            self._fps_timer = time.time()
        elif time.time() - self._fps_timer >= 5.0:
            elapsed = time.time() - self._fps_timer
            logger.info("[FPS] capture=%.1f", self._fps_counter / elapsed)
            self._fps_counter = 0
            self._fps_timer = time.time()

        # Saat video rewind (loop): flush stale frames + signal ke processing worker
        # untuk reset ByteTrack agar detection berjalan normal dari awal loop.
        if getattr(self.camera, "rewound", False):
            while not self.state.frame_queue.empty():
                try:
                    self.state.frame_queue.get_nowait()
                except queue.Empty:
                    break
            self.state.rewind_signal = True

        try:
            self.state.frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    def run_loop(self) -> None:
        self._sync_fps_from_camera()
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Unhandled error in FrameCaptureWorker.run_once")
                time.sleep(1)
