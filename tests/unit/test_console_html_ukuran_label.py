"""Settings: the size of the class label on the line video, set by support (user 2026-10-05).

"Ripe" / "Unripe" above each box on the line card read small from where the operator
stands. The size is a percentage of the drawing so far (100 = unchanged), saved with the
other grading settings and sent to every line, which applies it on the next frame.
"""
from __future__ import annotations

from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src" / "palmgrade" / "static" / "console.html").read_text(
    encoding="utf-8"
)


def _grup(kunci: str) -> str:
    awal = HTML.index(f'<div class="setelan-grup" data-setelan-grup="{kunci}">')
    return HTML[awal:HTML.index('<div class="setelan-grup" data-setelan-grup="dev">', awal)]


def test_kolom_ada_di_bagian_tampilan_video():
    grup = _grup("tampilan")
    assert 'id="set-ukuran-label"' in grup
    assert 'inputmode="numeric"' in grup and 'data-angka="bulat"' in grup
    assert '<button type="button" data-sub="tampilan" data-t="grupTampilan">' in HTML


def test_kolom_sebelum_tombol_simpan_setelan():
    """Saved by the same Save button as the other grading settings."""
    assert HTML.index('id="set-ukuran-label"') < HTML.index('id="set-simpan"')


def test_teks_kolom_ada_dua_bahasa():
    for kunci in ("grupTampilan", "labelUkuranLabel", "bantuUkuranLabel"):
        assert HTML.count(f"{kunci}:") == 2, f"{kunci} must exist in id and en"


def test_dimuat_dari_server_dengan_bawaan_seratus():
    muat = HTML.split("async function muatSetelan", 1)[1].split("\n}", 1)[0]
    assert '$("set-ukuran-label").value = r.ukuran_label ?? 100;' in muat


def test_dikirim_saat_simpan_dan_kolomnya_ditandai_kalau_ditolak():
    simpan = HTML.split('$("set-simpan").addEventListener', 1)[1].split("\n}));", 1)[0]
    assert 'ukuran_label: $("set-ukuran-label").value.replace(",", "."),' in simpan
    assert 'ukuran_label: "set-ukuran-label"' in simpan
