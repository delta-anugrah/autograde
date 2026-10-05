"""Where a detection box lands, and how thick it is drawn, on a frame of another size.

Batch 6.3: the operator stream is 1280x720 while the camera frame is 2448x2048.
`DisplayWorker` shrinks the frame FIRST and draws on the small one, so the boxes found on
the sensor frame are scaled here, together with the style `.env` wrote for the sensor frame.

Pure numbers: no cv2, so the unit suite covers it.
"""
from __future__ import annotations

from typing import NamedTuple

#: Scale of a frame that is drawn at its own size (the saved evidence photo).
TANPA_SKALA = (1.0, 1.0)

#: Gap between a box and its label, in pixels of the frame the style was written for.
JARAK_LABEL = 10


class GayaKotak(NamedTuple):
    """How a box and its label are drawn on one frame size."""

    border: int
    font_scale: float
    font_thickness: int
    jarak_label: int


def skala_ke(frame_width: int, frame_height: int, target_width: int, target_height: int) -> tuple[float, float]:
    """(sx, sy) from a frame to the target size. The two differ: 2448x2048 is not 16:9."""
    if frame_width <= 0 or frame_height <= 0:
        return TANPA_SKALA
    return target_width / frame_width, target_height / frame_height


def kotak_berskala(
    x1: int, y1: int, x2: int, y2: int, skala: tuple[float, float]
) -> tuple[int, int, int, int]:
    """The same box on the scaled frame."""
    if skala == TANPA_SKALA:
        return x1, y1, x2, y2
    sx, sy = skala
    return round(x1 * sx), round(y1 * sy), round(x2 * sx), round(y2 * sy)


def gaya_berskala(
    border: int, font_scale: float, font_thickness: int, skala: tuple[float, float]
) -> GayaKotak:
    """The style shrunk with the picture, never down to nothing.

    One factor for both axes (the geometric mean): a label keeps the area it had after the
    old draw-then-shrink, without being squashed flat like the picture is.
    """
    if skala == TANPA_SKALA:
        return GayaKotak(border, font_scale, font_thickness, JARAK_LABEL)
    faktor = (skala[0] * skala[1]) ** 0.5
    return GayaKotak(
        border=max(1, round(border * faktor)),
        font_scale=font_scale * faktor,
        font_thickness=max(1, round(font_thickness * faktor)),
        jarak_label=max(1, round(JARAK_LABEL * faktor)),
    )
