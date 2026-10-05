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
    gaya_berskala,
    gaya_label,
    kotak_berskala,
    skala_ke,
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
