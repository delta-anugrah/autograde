"""Box and label geometry for drawing on the stream-size frame (batch 6.3).

`DisplayWorker` used to draw the boxes on the full sensor frame and shrink the result. It now
shrinks first and draws small, so the box must land where it landed before and the label
must stay about as large as it was after the shrink.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.skala_tampilan import (
    JARAK_LABEL,
    TANPA_SKALA,
    GayaKotak,
    garis_berskala,
    gaya_berskala,
    gaya_label,
    kotak_berskala,
    skala_ke,
    ukuran_muat,
)

SENSOR = (2448, 2048)
STREAM = (1280, 720)


def test_skala_sensor_ke_stream_tidak_sama_di_dua_sumbu():
    sx, sy = skala_ke(*SENSOR, *STREAM)

    assert sx == pytest.approx(1280 / 2448)
    assert sy == pytest.approx(720 / 2048)


def test_frame_yang_sudah_seukuran_stream_tidak_diskala():
    assert skala_ke(*STREAM, *STREAM) == TANPA_SKALA == (1.0, 1.0)


@pytest.mark.parametrize("ukuran", [(0, 2048), (2448, 0)])
def test_frame_tanpa_ukuran_tidak_membagi_dengan_nol(ukuran):
    assert skala_ke(*ukuran, *STREAM) == TANPA_SKALA


def test_kotak_mendarat_di_tempat_yang_sama_sesudah_diskala():
    """A box drawn at (x, y) on the sensor frame showed at (x * sx, y * sy) on the stream."""
    skala = skala_ke(*SENSOR, *STREAM)

    assert kotak_berskala(0, 0, 2448, 2048, skala) == (0, 0, 1280, 720)
    assert kotak_berskala(1224, 1024, 2448, 2048, skala) == (640, 360, 1280, 720)
    assert kotak_berskala(500, 300, 1300, 1100, skala) == (261, 105, 680, 387)


def test_tanpa_skala_kotak_dan_gaya_tidak_berubah_sama_sekali():
    """The saved evidence photo is drawn at full size and must come out pixel for pixel as before."""
    assert kotak_berskala(501, 303, 1299, 1101, TANPA_SKALA) == (501, 303, 1299, 1101)
    assert gaya_berskala(8, 2.5, 5, TANPA_SKALA) == GayaKotak(8, 2.5, 5, JARAK_LABEL)
    assert JARAK_LABEL == 10


def test_gaya_mengecil_bersama_gambarnya():
    """`.env` on the factory PC sets the style for the 2448x2048 frame. Drawn unscaled on the
    1280x720 frame the border would be more than twice as thick and the label would cover
    the bunch."""
    gaya = gaya_berskala(8, 2.5, 5, skala_ke(*SENSOR, *STREAM))

    assert gaya.border == 3
    assert gaya.font_scale == pytest.approx(2.5 * (1280 / 2448 * 720 / 2048) ** 0.5)
    assert 1.0 < gaya.font_scale < 1.2
    assert gaya.font_thickness == 2
    assert gaya.jarak_label == 4


def test_garis_dan_huruf_tidak_pernah_hilang():
    """The default style (border 2, font thickness 2) must not round down to nothing."""
    gaya = gaya_berskala(2, 0.7, 2, skala_ke(*SENSOR, *STREAM))

    assert gaya.border >= 1 and gaya.font_thickness >= 1 and gaya.jarak_label >= 1
    assert gaya.font_scale > 0


# ── label size from the console (2026-10-05) ────────────────────────────────


def test_seratus_persen_tidak_mengubah_apa_pun():
    gaya = GayaKotak(3, 1.08, 2, 4)
    assert gaya_label(gaya, 100) == gaya


def test_persen_mengubah_tulisan_saja_bukan_garis_kotak():
    gaya = gaya_label(GayaKotak(3, 1.0, 2, 4), 200)

    assert gaya.border == 3, "the box border is not the label"
    assert gaya.font_scale == pytest.approx(2.0)
    assert gaya.font_thickness == 4
    assert gaya.jarak_label == 8, "a bigger label keeps its distance from the box"


def test_tulisan_kecil_tidak_pernah_hilang():
    gaya = gaya_label(GayaKotak(3, 1.0, 1, 4), 25)

    assert gaya.font_scale == pytest.approx(0.25)
    assert gaya.font_thickness == 1 and gaya.jarak_label >= 1


# ------------------------------------------------------------------ the picture keeps its ratio (2026-10-07)


@pytest.mark.parametrize(("frame", "hasil"), [
    ((1224, 1024), (861, 720)),   # Lampung Hikrobot with binning: 6:5, height decides
    ((2448, 2048), (861, 720)),   # the same camera without binning
    ((640, 480), (960, 720)),     # a 4:3 webcam
    ((1920, 1080), (1280, 720)),  # 16:9 fills the box exactly
    ((1280, 720), (1280, 720)),   # already stream size: unchanged
    ((1080, 1920), (405, 720)),   # a portrait photo
    ((2000, 500), (1280, 320)),   # wider than 16:9: width decides
])
def test_ukuran_muat_menjaga_rasio_di_dalam_kotak_stream(frame, hasil):
    """The stream used to be forced to 1280x720, so a 1224x1024 camera showed ~1.49x too wide.
    Now the picture keeps its own ratio inside that box: never stretched, never cropped."""
    assert ukuran_muat(*frame, *STREAM) == hasil


@pytest.mark.parametrize("ukuran", [(0, 1024), (1224, 0)])
def test_ukuran_muat_tanpa_ukuran_kembali_ke_kotak(ukuran):
    assert ukuran_muat(*ukuran, *STREAM) == STREAM


def test_garis_tegak_diskalakan_lebar_garis_mendatar_tinggi():
    """The capture line is stored in settings space (1280x720) and drawn on the smaller picture:
    an upright line moves with the width, a flat one with the height (the 2026-09 bug class)."""
    skala = (861 / 1280, 720 / 720)

    assert garis_berskala(640, False, skala) == 430  # 430.5, round half to even
    assert garis_berskala(360, True, skala) == 360
    assert garis_berskala(0, False, skala) == 0, "0 = no line, and stays no line"
    assert garis_berskala(640, False, TANPA_SKALA) == 640


def test_garis_kecil_tidak_hilang_dari_gambar_sesudah_diskala():
    """A flat line at 1 on a 2000x500 source (scale 0.44) must stay a line on screen: detection
    still uses it, so drawing nothing would hide a working capture line."""
    assert garis_berskala(1, True, (1.0, 320 / 720)) == 1


# ── Overlay shapes from the console design (2026-10-08) ─────────────────────────────────────
# The new console mockup draws the FPS as a dark pill in the picture's top-right corner (the
# card's "Line 1" chip covers the top-left) and each detection label as a filled pill in the box
# colour, sitting on the box's top-left corner. v1.26.1 still drew bare text for both.


def test_fps_pill_sits_in_the_top_right_corner():
    from palmgrade.domain.skala_tampilan import TEPI_FPS, pil_fps

    (x1, y1, x2, y2), (tx, ty) = pil_fps(861, 90, 20)

    assert x2 == 861 - TEPI_FPS and y1 == TEPI_FPS
    assert x1 < tx < tx + 90 < x2, "the text is inside the pill, with room on both sides"
    assert y1 < ty - 20 and ty < y2, "the text is inside the pill, with room above and below"


def test_fps_pill_never_starts_left_of_the_margin_on_a_tiny_picture():
    from palmgrade.domain.skala_tampilan import TEPI_FPS, pil_fps

    (x1, _, _, _), _ = pil_fps(60, 90, 20)

    assert x1 == TEPI_FPS


def test_label_pill_sits_on_the_box_top_left_corner():
    from palmgrade.domain.skala_tampilan import pil_label

    (x1, y1, x2, y2), (tx, ty) = pil_label(200, 300, 60, 20, jarak=3, lebar_gambar=1280)

    assert x1 == 200 and y2 == 300 - 3, "left edge on the box's left edge, just above its top"
    assert x1 < tx and tx + 60 < x2
    assert y1 < ty - 20 and ty < y2


def test_label_pill_goes_inside_the_box_when_there_is_no_room_above():
    from palmgrade.domain.skala_tampilan import pil_label

    (_, y1, _, y2), (_, ty) = pil_label(200, 10, 60, 20, jarak=3, lebar_gambar=1280)

    assert y1 == 10 + 3 and ty < y2


def test_label_pill_is_pulled_back_inside_the_right_edge():
    from palmgrade.domain.skala_tampilan import pil_label

    (x1, _, x2, _), _ = pil_label(1250, 300, 60, 20, jarak=3, lebar_gambar=1280)

    assert x2 <= 1280 and x1 >= 0


def test_box_corner_radius_grows_with_the_border_but_never_swallows_a_small_box():
    from palmgrade.domain.skala_tampilan import jari_kotak

    assert jari_kotak(3, 400, 400) > jari_kotak(1, 400, 400) > 0
    assert jari_kotak(8, 20, 400) <= 5
