"""Header and update box polish (user 2026-10-04).

The language, theme and sign-out buttons carry an icon so a newcomer knows what they do
without reading the word; the brand dot is a circle centred on AUTOGRADE; and the "release
every truck first" condition under Update now is coloured, because missing it is what makes
the install refuse.
"""

from __future__ import annotations

import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada (image CI)")


def _aturan(selector: str) -> str:
    awal = HTML.find("\n  " + selector + " {")
    assert awal != -1, f"aturan CSS `{selector}` tidak ada"
    return HTML[awal : HTML.find("}", awal)]


@pytest.mark.parametrize("id_", ["bahasa", "tema", "keluar"])
def test_tombol_kepala_berikon_dan_teksnya_di_span(id_):
    tag = re.search(rf'<button[^>]*id="{id_}"[^>]*>(.*?)</button>', HTML, re.S)
    assert tag, id_
    isi = tag.group(1)
    assert "<svg" in isi and 'aria-hidden="true"' in isi, isi
    assert f'id="{id_}-teks"' in isi, isi


def test_teks_tombol_diganti_lewat_span_bukan_menghapus_ikon():
    # `textContent` on the button itself would wipe the icon on every language or theme switch.
    assert '$("tema").textContent' not in HTML
    assert '$("bahasa").textContent' not in HTML
    assert '$("tema-teks").textContent' in HTML and '$("bahasa-teks").textContent' in HTML


def test_ikon_tombol_kepala_di_tengah_vertikal():
    aturan = _aturan(".tombol-ikon")
    assert "display:inline-flex" in aturan and "align-items:center" in aturan


def test_logo_bulat_di_tengah():
    titik = _aturan("h1::before")
    lebar = re.search(r"width:([^;]+);", titik).group(1)
    tinggi = re.search(r"height:([^;]+);", titik).group(1)
    assert lebar == tinggi and "border-radius:50%" in titik
    assert "align-items:center" in _aturan("h1")


@butuh_node
def test_syarat_restart_berwarna():
    ikon = "const IKON_UNDUH = '<svg></svg>';"
    siap = "{terpasang:true, siap:'v1.23.0', berjalan:false, hasil:null}"
    html = jalankan(["tombolPasang", "teksHasilPembaruan", "htmlPembaruan"], f"htmlPembaruan({siap}, false)", tambahan=ikon)
    assert 'class="pembaruan-syarat"' in html and "dilepas otomatis" in html
    assert "color:var(--warn)" in _aturan(".pembaruan-syarat")
