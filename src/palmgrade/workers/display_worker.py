from __future__ import annotations

import logging
import time

import cv2

from ..core.config import Settings
from ..core.constants import JPEG_QUALITY_STREAM, REF_LINE_THICKNESS
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

    def _draw_zone_lines(self, frame) -> None:
        h, w, _ = frame.shape
        d = self.settings.conveyor_direction
        entry_off = self.settings.detection_entry_offset
        exit_off = self.settings.detection_exit_offset

        if d in ("rtl", "ltr"):
            entry_x = max(0, w - entry_off) if d == "rtl" else min(w, entry_off)
            exit_x = min(w, exit_off) if d == "rtl" else max(0, w - exit_off)
            cv2.line(frame, (entry_x, 0), (entry_x, h), (255, 0, 0), REF_LINE_THICKNESS)  # blue = entry
            cv2.line(frame, (exit_x, 0), (exit_x, h), (0, 255, 0), REF_LINE_THICKNESS)    # green = exit
        else:  # ttb, btt
            entry_y = min(h, entry_off) if d == "ttb" else max(0, h - entry_off)
            exit_y = max(0, h - exit_off) if d == "ttb" else min(h, exit_off)
            cv2.line(frame, (0, entry_y), (w, entry_y), (255, 0, 0), REF_LINE_THICKNESS)
            cv2.line(frame, (0, exit_y), (w, exit_y), (0, 255, 0), REF_LINE_THICKNESS)

    def run_once(self) -> None:
        now = time.time()
        wait = self._frame_interval - (now - self._last_render_time)
        if wait > 0:
            time.sleep(wait)
        self._last_render_time = time.time()

        frame = self.state.latest_raw_frame
        if frame is None:
            return

        display = frame.copy()
        results = self.state.last_yolo_results
        if results is not None:
            display = self.pipeline.draw_boxes(display, results)
        self._draw_zone_lines(display)

        target_w = self.settings.stream_width
        target_h = self.settings.stream_height
        h, w = display.shape[:2]
        if w != target_w or h != target_h:
            display = cv2.resize(display, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

        _, buf = cv2.imencode(".jpg", display, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY_STREAM])
        with self.state.frame_condition:
            self.state.latest_frame = buf.tobytes()
            self.state.frame_condition.notify_all()

    def run_loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Unhandled error in DisplayWorker.run_once")
                time.sleep(1)
