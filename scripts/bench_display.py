"""Benchmark for batch 6.3: one render of the operator stream.

    .venv/bin/python scripts/bench_display.py

Real cv2 and the real `RealtimeInspectionPipeline` drawing code on a sensor-size frame
(`images/sample_sawit.jpg` enlarged to 2448x2048), with boxes handed in as plain objects (no
model, no GPU, no camera). Three ways are timed:

* old: copy the full frame, draw the boxes on it, shrink, draw line and ROI, encode;
* new: the real `DisplayWorker.run_once` with one viewer (shrink first, draw small);
* new, nobody watching: the real `DisplayWorker.run_once` with no viewer.

Not a test and never run by CI: it imports cv2 and torch. The numbers are per render; a line
renders `STREAM_FPS` times a second (12 by default). A Mac gives Mac numbers: memory speed
decides what copying 14.3 MB costs, so run it on the factory PC before quoting a factory number.
On a GPU the boxes are also read from the device per render; that part is not measured here.
"""
from __future__ import annotations

import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

import cv2

AKAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AKAR / "src"))

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.core.constants import JPEG_QUALITY_STREAM  # noqa: E402
from palmgrade.pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline  # noqa: E402
from palmgrade.workers.display_worker import DisplayWorker  # noqa: E402
from palmgrade.workers.runtime_state import RuntimeState  # noqa: E402

SENSOR = (2448, 2048)
STREAM = (1280, 720)
PUTARAN = 400
FPS_STREAM = 12
NAMA = {0: "JK", 1: "Ripe", 2: "TP", 3: "Unripe"}


class _Registry:
    device = "cpu"
    model = None


class _Nilai(list):
    def tolist(self):
        return list(self)

    def item(self):
        return self[0]


class _Box:
    def __init__(self, xyxy, cls_id: int) -> None:
        self.xyxy = [_Nilai(xyxy)]
        self.cls = [_Nilai([cls_id])]
        self.conf = [_Nilai([0.9])]
        self.id = None


class _Hasil:
    def __init__(self, jumlah: int, ukuran: tuple[int, int]) -> None:
        lebar, tinggi = ukuran
        self.names = NAMA
        self.boxes = [
            _Box((lebar * (0.05 + 0.15 * i), tinggi * 0.2, lebar * (0.18 + 0.15 * i), tinggi * 0.7), 1 if i % 2 == 0 else 3)
            for i in range(jumlah)
        ]


def _settings() -> Settings:
    # The style used for the 2448x2048 frame, a capture line and an ROI box, as on a line.
    return replace(
        Settings(), stream_width=STREAM[0], stream_height=STREAM[1],
        border_thickness=8, font_scale=2.5, font_thickness=5,
        roi_x1=100, roi_y1=80, roi_x2=1180, roi_y2=640, garis_capture=300, sumbu_garis="tegak",
    )


def _render_lama(pipeline: RealtimeInspectionPipeline, settings: Settings, frame, results) -> bytes:
    """`DisplayWorker.run_once` before 6.3, step for step."""
    display = frame.copy()
    display = pipeline.draw_boxes(display, results, tampilkan_confidence=False)
    tinggi, lebar = display.shape[:2]
    if (lebar, tinggi) != STREAM:
        display = cv2.resize(display, STREAM, interpolation=cv2.INTER_NEAREST)
    display = pipeline.draw_roi(display, garis_capture=settings.garis_capture, sumbu=settings.sumbu_garis)
    cv2.putText(display, "12 FPS", (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(display, "12 FPS", (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)
    _, buf = cv2.imencode(".jpg", display, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY_STREAM])
    return buf.tobytes()


def _median_ms(*fungsi) -> list[float]:
    """Median per function. The functions take turns render by render, so a busy moment on
    the machine lands on all of them and not on whichever happened to run then."""
    for f in fungsi:
        f()
    hasil: list[list[float]] = [[] for _ in fungsi]
    for _ in range(PUTARAN):
        for i, f in enumerate(fungsi):
            mulai = time.perf_counter()
            f()
            hasil[i].append(time.perf_counter() - mulai)
    return [statistics.median(h) * 1000 for h in hasil]


def _pekerja(pipeline, settings, frame, results, *, penonton: bool) -> DisplayWorker:
    state = RuntimeState()
    state.last_yolo_frame = frame
    state.last_yolo_results = results
    state.last_yolo_frame_at = 1_000.0
    state.inference_fps = 12.0
    if penonton:
        state.penonton_masuk()
    return DisplayWorker(
        state=state, pipeline=pipeline, settings=settings, target_fps=FPS_STREAM,
        jam=lambda: 1_000.0, tidur=lambda _detik: None,
    )


def main() -> None:
    settings = _settings()
    pipeline = RealtimeInspectionPipeline(_Registry(), settings)
    kecil = cv2.imread(str(AKAR / "images" / "sample_sawit.jpg"))
    print(f"cv2 {cv2.__version__}, {PUTARAN} renders, median, milliseconds per render\n")
    print(f"{'source frame':<16}{'boxes':>6}{'old':>9}{'new':>9}{'saved':>9}{'new, nobody watching':>24}")
    for ukuran in (SENSOR, STREAM):
        frame = cv2.resize(kecil, ukuran, interpolation=cv2.INTER_CUBIC)
        for jumlah in (0, 2, 6):
            results = _Hasil(jumlah, ukuran)
            lama, baru, kosong = _median_ms(
                lambda f=frame, r=results: _render_lama(pipeline, settings, f, r),
                _pekerja(pipeline, settings, frame, results, penonton=True).run_once,
                _pekerja(pipeline, settings, frame, results, penonton=False).run_once,
            )
            print(
                f"{ukuran[0]}x{ukuran[1]:<11}{jumlah:>6}{lama:>9.2f}{baru:>9.2f}{lama - baru:>9.2f}{kosong:>24.4f}"
            )
    print(f"\nper second at {FPS_STREAM} renders: multiply by {FPS_STREAM}")


if __name__ == "__main__":
    main()
