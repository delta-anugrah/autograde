from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..core.config import Settings
from ..core.constants import JPEG_QUALITY_STREAM
from ..domain.setelan_grading import UKURAN_LABEL_BAWAAN
from ..domain.skala_tampilan import TANPA_SKALA, skala_ke, ukuran_muat
from .runtime_state import RuntimeState

if TYPE_CHECKING:  # annotation only: the pipeline module pulls in cv2 and ultralytics, and
    # the unit suite runs this worker without either (the pipeline is injected).
    from ..pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline

logger = logging.getLogger(__name__)

#: A YOLO frame older than this is no longer drawn with its boxes: on a slow model (CPU) the
#: fruit has moved on, and the stream falls back to the raw frame so it does not freeze.
_SEGAR_S = 0.5


class DisplayWorker:
    """Dedicated MJPEG render thread.

    Reads latest_raw_frame + last_yolo_results from state, draws zone lines and
    detection boxes, then pushes encoded JPEG to latest_frame so all MJPEG clients
    get a consistent, smooth stream independent of YOLO timing.

    Since batch 6.3 it does the least it can:

    * nobody reading the stream (`state.penonton_stream == 0`) = nothing is rendered at all;
    * the frame is shrunk to stream size FIRST and everything is drawn on the small frame,
      so the camera frame (1224x1024 at Lampung, 2448x2048 without binning) is neither copied nor
      drawn on.

    `cv` is the `cv2` module; it is an argument so the unit suite can run the worker without
    OpenCV (CLAUDE.md § Tests). Left out, the real one is imported here, on first use.
    """

    def __init__(
        self,
        state: RuntimeState,
        pipeline: RealtimeInspectionPipeline,
        settings: Settings,
        target_fps: int = 24,
        *,
        cv: Any = None,
        jam: Callable[[], float] = time.time,
        tidur: Callable[[float], None] = time.sleep,
    ) -> None:
        self.state = state
        self.pipeline = pipeline
        self.settings = settings
        if cv is None:
            import cv2 as cv
        self._cv = cv
        self._jam = jam
        self._tidur = tidur
        self._frame_interval = 1.0 / max(1, target_fps)
        self._last_render_time: float = 0.0
        self._fps_counter: int = 0
        self._fps_timer: float = 0.0
        self._display_fps: float = 0.0

    def run_once(self) -> None:
        now = self._jam()
        wait = self._frame_interval - (now - self._last_render_time)
        if wait > 0:
            self._tidur(wait)
        self._last_render_time = self._jam()

        if self.state.penonton_stream <= 0:
            self._istirahat()
            return

        # Pakai last_yolo_frame jika fresh (< 500ms) supaya box selalu aligned.
        # Kalau YOLO lambat (CPU), fallback ke raw frame biar stream tidak freeze.
        yolo_frame = self.state.last_yolo_frame
        yolo_fresh = (self._jam() - self.state.last_yolo_frame_at) < _SEGAR_S
        if yolo_frame is not None and yolo_fresh:
            sumber = yolo_frame
            use_boxes = True
        else:
            sumber = self.state.latest_raw_frame
            if sumber is None:
                return
            use_boxes = False  # box tidak di-render di raw frame — posisi tidak aligned

        display, skala = self._ke_ukuran_stream(sumber)

        results = self.state.last_yolo_results
        if use_boxes and results is not None:
            display = self.pipeline.draw_boxes(
                display, results,
                tampilkan_confidence=(
                    self.state.mode_dev_override
                    if self.state.mode_dev_override is not None
                    else self.settings.mode_dev
                ),
                skala=skala,
                ukuran_label=self.state.ukuran_label_override or UKURAN_LABEL_BAWAAN,
            )

        # Garis capture dan ROI disimpan dalam ruang SETELAN (`STREAM_WIDTH` x
        # `STREAM_HEIGHT`, tempat operator menyetelnya) dan tetap berarti begitu; sejak
        # 2026-10-07 gambarnya menjaga rasio kamera, jadi angkanya dipetakan per sumbu ke
        # gambar ini saat digambar. Dibaca dari `RuntimeState` tiap render supaya perubahan
        # dari konsol langsung terlihat tanpa restart line.
        tinggi_gambar, lebar_gambar = display.shape[:2]
        display = self.pipeline.draw_roi(
            display,
            garis_capture=(
                self.state.garis_capture_override
                if self.state.garis_capture_override is not None
                else self.settings.garis_capture
            ),
            sumbu=(
                self.state.sumbu_garis_override
                if self.state.sumbu_garis_override is not None
                else self.settings.sumbu_garis
            ),
            tampil_garis=self.state.tampil_garis_override is not False,
            tampil_roi=self.state.tampil_roi_override is not False,
            roi=self.state.roi_override,
            skala_setelan=skala_ke(
                self.settings.stream_width, self.settings.stream_height, lebar_gambar, tinggi_gambar
            ),
        )

        # YOLO inference FPS overlay (from FrameProcessingWorker; drawn in stream space → fixed, always readable)
        cv = self._cv
        fps_text = f"{self.state.inference_fps:.0f} FPS"
        cv.putText(display, fps_text, (12, 36), cv.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5, cv.LINE_AA)
        cv.putText(display, fps_text, (12, 36), cv.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv.LINE_AA)

        _, buf = cv.imencode(".jpg", display, [int(cv.IMWRITE_JPEG_QUALITY), JPEG_QUALITY_STREAM])
        with self.state.frame_condition:
            self.state.latest_frame = buf.tobytes()
            self.state.frame_condition.notify_all()

        self._fps_counter += 1
        fps_now = self._jam()
        if self._fps_timer == 0.0:
            self._fps_timer = fps_now
        elif fps_now - self._fps_timer >= 1.0:
            self._display_fps = self._fps_counter / (fps_now - self._fps_timer)
            self._fps_counter = 0
            self._fps_timer = fps_now

    def _ke_ukuran_stream(self, frame: Any) -> tuple[Any, tuple[float, float]]:
        """A stream-size frame that is safe to draw on, and the scale that led to it.

        Stream size keeps the frame's own ratio inside `STREAM_WIDTH` x `STREAM_HEIGHT`
        (2026-10-07): 1224x1024 becomes 861x720, never stretched to 16:9 again.

        `frame` is shared with the detection thread (and, for a captured bunch, with the
        photo writer as the clean copy), so it is never drawn on. Shrinking already makes a
        new array; only a frame that is stream size already has to be copied.
        """
        h, w = frame.shape[:2]
        target_w, target_h = ukuran_muat(w, h, self.settings.stream_width, self.settings.stream_height)
        if w == target_w and h == target_h:
            return frame.copy(), TANPA_SKALA
        kecil = self._cv.resize(frame, (target_w, target_h), interpolation=self._cv.INTER_NEAREST)
        return kecil, skala_ke(w, h, target_w, target_h)

    def _istirahat(self) -> None:
        """Nobody reads the stream: render nothing, and drop the last picture so a viewer who
        comes back waits one interval for a new frame, never served the old one. Still this
        worker writing `latest_frame`, under the same condition (rule 4)."""
        if self.state.latest_frame is None:
            return
        with self.state.frame_condition:
            self.state.latest_frame = None

    def run_loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("Unhandled error in DisplayWorker.run_once")
                time.sleep(1)
