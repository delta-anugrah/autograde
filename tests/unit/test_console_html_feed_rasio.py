"""The camera box shows the whole picture at its own shape (2026-10-07, new console PR 1).

The line now keeps the camera ratio (861x720 for the 1224x1024 Lampung camera, 960x720 for a
4:3 webcam). The console box used to be a fixed 16:9 with `object-fit: cover`: any other ratio
would be cut. Now the box takes the ratio of the first frame it receives, remembers it per
line across card redraws, and shows the picture with `contain`, so nothing is ever cut or
stretched. A portrait source is capped by `max-height` and letterboxed, never cropped.
"""
from __future__ import annotations

import re

from konsol_js import HTML


def _aturan(selektor: str) -> str:
    cocok = re.search(rf"\n  {re.escape(selektor)} \{{([^}}]*)\}}", HTML)
    assert cocok, f"no CSS rule for {selektor}"
    return cocok.group(1).replace(" ", "")


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal:HTML.index("\n}\n", awal)]


def test_gambar_kamera_tidak_pernah_dipotong():
    aturan = _aturan(".feed img")
    assert "object-fit:contain" in aturan
    assert "cover" not in aturan, "cover cuts any picture whose ratio differs from the box"


def test_kotak_kamera_dibatasi_tinggi_layar():
    """A portrait photo source must not make one card taller than the window."""
    assert "max-height:" in _aturan(".feed")


def test_rasio_diambil_dari_gambar_pertama_dan_diingat_per_line():
    memuat = _fungsi("feedMemuat")
    assert "naturalWidth" in memuat and "naturalHeight" in memuat
    assert "rasioFeed.set(" in memuat
    assert "const rasioFeed = new Map()" in HTML


def test_kartu_yang_digambar_ulang_memakai_rasio_yang_diingat():
    """Cards are redrawn by the polls; without this the box would jump back to 16:9 each time."""
    assert "gayaRasioFeed(l.line_code)" in _fungsi("kartuLine")
    gaya = _fungsi("gayaRasioFeed")
    assert "rasioFeed.get(" in gaya and "aspect-ratio:" in gaya


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _teks(bahasa: str, kunci: str) -> str:
    return re.search(rf'\b{kunci}:"([^"]*)"', _kamus(bahasa)).group(1)


def test_petunjuk_roi_dan_garis_tidak_lagi_menyebut_piksel_video():
    """The picture is 861x720 on the Lampung camera since 2026-10-07, but the stored numbers stay
    on the 1280x720 settings grid. A hint that says "pixels on the video" makes a technician
    read 430 off the picture for the middle, which lands a third of the way in, silently."""
    for kunci in ("bantuKotak", "bantuGarisTegak", "bantuGarisMendatar"):
        assert "Piksel" not in _teks("id", kunci), kunci
        assert "Pixels" not in _teks("en", kunci), kunci
    assert "1280" in _teks("id", "bantuKotak") and "seluruh gambar" in _teks("id", "bantuKotak")
    assert "1280" in _teks("en", "bantuKotak") and "whole picture" in _teks("en", "bantuKotak")
    assert "1280" in _teks("id", "bantuGarisTegak") and "720" in _teks("id", "bantuGarisMendatar")
    assert "1280" in _teks("en", "bantuGarisTegak") and "720" in _teks("en", "bantuGarisMendatar")
