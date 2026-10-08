"""Where a detection box lands, and how thick it is drawn, on a frame of another size.

Batch 6.3: the operator stream fits inside 1280x720 (861x720 since 2026-10-07, the camera's own
ratio) while the camera frame is 1224x1024 at Lampung
(binning 2x2 in `config/camera/hikrobot.mfs`; 2448x2048 without it).
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
    """(sx, sy) from a frame to the target size. The two differ: the camera frame is not 16:9."""
    if frame_width <= 0 or frame_height <= 0:
        return TANPA_SKALA
    return target_width / frame_width, target_height / frame_height


def ukuran_muat(lebar: int, tinggi: int, kotak_lebar: int, kotak_tinggi: int) -> tuple[int, int]:
    """The largest size with the frame's own ratio that fits inside the stream box (2026-10-07).

    The stream used to be forced to the box itself (`STREAM_WIDTH` x `STREAM_HEIGHT`), so the
    1224x1024 Lampung camera showed about 1.49x too wide and a 4:3 webcam 1.33x. Now the picture
    keeps its ratio: 1224x1024 -> 861x720, 640x480 -> 960x720, 1920x1080 -> 1280x720. A frame
    with no size gets the box, as before.
    """
    if lebar <= 0 or tinggi <= 0 or kotak_lebar <= 0 or kotak_tinggi <= 0:
        return kotak_lebar, kotak_tinggi
    if lebar * kotak_tinggi >= tinggi * kotak_lebar:  # wider than the box: the width decides
        return kotak_lebar, max(1, round(tinggi * kotak_lebar / lebar))
    return max(1, round(lebar * kotak_tinggi / tinggi)), kotak_tinggi


def garis_berskala(garis: int, mendatar: bool, skala: tuple[float, float]) -> int:
    """The capture line from settings space to the picture it is drawn on.

    An upright line is an x and moves with the width, a flat one is a y and moves with the
    height. `0` stays `0`: no line.
    """
    if garis <= 0 or skala == TANPA_SKALA:
        return garis
    # Never rounded away: detection still uses a small line, so the screen must show it.
    return max(1, round(garis * (skala[1] if mendatar else skala[0])))


def kotak_berskala(
    x1: int, y1: int, x2: int, y2: int, skala: tuple[float, float]
) -> tuple[int, int, int, int]:
    """The same box on the scaled frame."""
    if skala == TANPA_SKALA:
        return x1, y1, x2, y2
    sx, sy = skala
    return round(x1 * sx), round(y1 * sy), round(x2 * sx), round(y2 * sy)


def gaya_label(gaya: GayaKotak, persen: int) -> GayaKotak:
    """The label text at `persen` of its size, set by support from the console (2026-10-05).

    Only the text grows or shrinks, with its stroke and its distance from the box; the box
    border stays. 100 returns the style unchanged.
    """
    if persen == 100:
        return gaya
    faktor = persen / 100
    return gaya._replace(
        font_scale=gaya.font_scale * faktor,
        font_thickness=max(1, round(gaya.font_thickness * faktor)),
        jarak_label=max(1, round(gaya.jarak_label * faktor)),
    )


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


# ── Overlay shapes from the console design (2026-10-08) ─────────────────────────────────────
# The console mockup draws the FPS as a dark pill in the top-right corner and each detection
# label as a filled pill in the box colour on the box's top-left corner. These are the numbers;
# `RealtimeInspectionPipeline` does the drawing.

Kotak = tuple[int, int, int, int]
Titik = tuple[int, int]

#: Space between the FPS pill and the picture's top and right edges, in stream pixels.
TEPI_FPS = 12


def pil_fps(lebar_gambar: int, lebar_teks: int, tinggi_teks: int) -> tuple[Kotak, Titik]:
    """The FPS pill (x1, y1, x2, y2) and where its text starts (baseline).

    Top-right because the console's line card floats its name chip over the top-left corner.
    On a picture narrower than the pill it falls back to the left margin.
    """
    pad_x, pad_y = round(tinggi_teks * 0.8), round(tinggi_teks * 0.55)
    lebar, tinggi = lebar_teks + 2 * pad_x, tinggi_teks + 2 * pad_y
    x1 = max(TEPI_FPS, lebar_gambar - TEPI_FPS - lebar)
    y1 = TEPI_FPS
    return (x1, y1, x1 + lebar, y1 + tinggi), (x1 + pad_x, y1 + pad_y + tinggi_teks)


def pil_label(
    x1: int, y1: int, lebar_teks: int, tinggi_teks: int, *, jarak: int, lebar_gambar: int
) -> tuple[Kotak, Titik]:
    """The label pill of a box whose top-left corner is (x1, y1), and where its text starts.

    Left edge on the box's left edge, `jarak` above its top. A box touching the top of the
    picture gets the pill just inside its top instead, and a box at the right edge pulls the
    pill back in, so the class name is never cut off. The bottom padding holds the descender
    ("p" in Ripe).
    """
    pad_x, pad_y = round(tinggi_teks * 0.55), round(tinggi_teks * 0.45)
    lebar, tinggi = lebar_teks + 2 * pad_x, tinggi_teks + 2 * pad_y
    atas = y1 - jarak - tinggi
    if atas < 0:
        atas = y1 + jarak
    kiri = max(0, min(x1, lebar_gambar - lebar))
    return (kiri, atas, kiri + lebar, atas + tinggi), (kiri + pad_x, atas + pad_y + tinggi_teks)


def jari_kotak(border: int, lebar: int, tinggi: int) -> int:
    """Corner radius of a detection box: grows with its border, never past a quarter of a side."""
    return max(0, min(2 * border + 3, lebar // 4, tinggi // 4))
