from __future__ import annotations

import logging
import time

import cv2

from ..core.config import Settings
from ..core.constants import JPEG_QUALITY_STREAM
from ..pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline
from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class DisplayWorker:
    """Dedicated MJPEG render thread.

    Reads latest_raw_frame + last_yolo_results from state, draws zone lines and
    detection boxes, then pushes encoded JPEG to latest_frame so all MJPEG clients
    get a consistent, smooth stream independent of YOLO timing.
    """

    def __init__(
        self,
        state: RuntimeState,
        pipeline: RealtimeInspectionPipeline,
        settings: Settings,
        target_fps: int = 24,
    ) -> None:
        self.state = state
        self.pipeline = pipeline
        self.settings = settings
        self._frame_interval = 1.0 / max(1, target_fps)
        self._last_render_time: float = 0.0
        self._fps_counter: int = 0
        self._fps_timer: float = 0.0

    def run_once(self) -> None:
        now = time.time()
        wait = self._frame_interval - (now - self._last_render_time)
        if wait > 0:
            time.sleep(wait)
        self._last_render_time = time.time()

        # Pakai last_yolo_frame jika fresh (< 500ms) supaya box selalu aligned.
        # Kalau YOLO lambat (CPU), fallback ke raw frame biar stream tidak freeze.
        yolo_frame = self.state.last_yolo_frame
        yolo_fresh = (time.time() - self.state.last_yolo_frame_at) < 0.5
        if yolo_frame is not None and yolo_fresh:
            display = yolo_frame.copy()
            use_boxes = True
        else:
            frame = self.state.latest_raw_frame
            if frame is None:
                return
            display = frame.copy()
            use_boxes = False  # box tidak di-render di raw frame — posisi tidak aligned

        display = self.pipeline.draw_roi(display)
        results = self.state.last_yolo_results
        if use_boxes and results is not None:
            display = self.pipeline.draw_boxes(display, results)

        target_w = self.settings.stream_width
        target_h = self.settings.stream_height
        h, w = display.shape[:2]
        if w != target_w or h != target_h:
            display = cv2.resize(display, (target_w, target_h), interpolation=cv2.INTER_NEAREST)

        _, buf = cv2.imencode(".jpg", display, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY_STREAM])
        with self.state.frame_condition:
            self.state.latest_frame = buf.tobytes()
            self.state.frame_condition.notify_all()

        self._fps_counter += 1
        if self._fps_timer == 0.0:
            self._fps_timer = time.time()
        elif time.time() - self._fps_timer >= 5.0:
            elapsed = time.time() - self._fps_timer
            logger.info("[FPS] display=%.1f", self._fps_counter / elapsed)
            self._fps_counter = 0
            self._fps_timer = time.time()

    def run_loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Unhandled error in DisplayWorker.run_once")
                time.sleep(1)
