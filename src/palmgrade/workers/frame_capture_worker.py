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
    def __init__(self, camera: CameraSource, state: RuntimeState, target_fps: int = 20, device_index: int = 0, serial: str | None = None, feature_file: str | None = None, **_) -> None:
        self.camera = camera
        self.state = state
        self._device_index = device_index
        self._serial = serial
        self._feature_file = feature_file
        self._target_fps = target_fps
        self._frame_interval = 1.0 / max(1, target_fps) if target_fps > 0 else 0.0
        self._last_frame_time: float = 0.0
        self._consecutive_failures: int = 0
        self._reconnect_backoff: float = _RECONNECT_BACKOFF_BASE
        self._fps_counter: int = 0
        self._fps_timer: float = 0.0
        self._exhausted_logged: bool = False

    @property
    def frame_interval(self) -> float:
        """Seconds between grabs. 0 = grab as fast as the camera hands frames over."""
        return self._frame_interval

    def adopt_camera_frame_rate(self) -> None:
        """Let the camera decide the pace, so the rate lives in ONE place.

        On a Hikrobot line that place is the `.mfs` pushed to the camera on
        every connect (`CAMERA_FEATURE_FILE`), and reading the rate back from
        the camera is what keeps `CAMERA_FPS` from quietly becoming a second
        setting: pacing slower than the camera used to throttle it, while
        pacing faster did nothing at all.

        `CAMERA_FPS` stays the fallback for sources that cannot report a rate —
        a webcam or a video file.
        """
        detected = self.camera.get_fps()
        if detected > 0:
            self._frame_interval = 1.0 / detected
            logger.info("Capture paced by the camera: %.2f fps", detected)
            return
        self._frame_interval = 1.0 / self._target_fps if self._target_fps > 0 else 0.0
        logger.info(
            "Camera reports no frame rate — pacing from CAMERA_FPS=%s", self._target_fps
        )

    def _try_reconnect(self) -> None:
        logger.warning("Camera: %d consecutive failures — attempting reconnect", self._consecutive_failures)
        try:
            self.camera.disconnect()
        except Exception:
            pass
        time.sleep(self._reconnect_backoff)
        self._reconnect_backoff = min(self._reconnect_backoff * 2, _RECONNECT_BACKOFF_MAX)
        try:
            self.camera.connect(index=self._device_index, serial=self._serial, feature_file=self._feature_file)
            self._consecutive_failures = 0
            self._reconnect_backoff = _RECONNECT_BACKOFF_BASE
            self.adopt_camera_frame_rate()
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
                time.sleep(0.1)
            return

        self._exhausted_logged = False
        self._consecutive_failures = 0
        self._reconnect_backoff = _RECONNECT_BACKOFF_BASE
        self.state.latest_raw_frame = frame

        self._fps_counter += 1
        if self._fps_timer == 0.0:
            self._fps_timer = time.time()
        else:
            fps_now = time.time()
            if fps_now - self._fps_timer >= 5.0:
                logger.info("[FPS] capture=%.1f", self._fps_counter / (fps_now - self._fps_timer))
                self._fps_counter = 0
                self._fps_timer = fps_now

        # Saat video rewind (loop): flush stale frames + signal ke processing worker
        # untuk reset ByteTrack agar detection berjalan normal dari awal loop.
        if self.camera.rewound:
            while not self.state.frame_queue.empty():
                try:
                    self.state.frame_queue.get_nowait()
                except queue.Empty:
                    break
            self.state.rewind_signal = True

        # Drop-oldest policy: hapus frame paling lama dulu baru masukkan frame terbaru.
        # Ini memastikan processing worker selalu dapat frame terbaru, bukan frame stale.
        try:
            self.state.frame_queue.put_nowait(frame)
        except queue.Full:
            try:
                self.state.frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.state.frame_queue.put_nowait(frame)
            except queue.Full:
                pass

    def run_loop(self) -> None:
        self.adopt_camera_frame_rate()
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Unhandled error in FrameCaptureWorker.run_once")
                time.sleep(1)
