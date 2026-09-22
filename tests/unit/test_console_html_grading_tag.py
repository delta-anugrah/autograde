"""Invarian HTML tab Grading: badge hasil dan kode line.

Konsol tidak punya test runner JS, jadi yang bisa dijaga di CI adalah bahwa
aturan dan elemen yang dipakai skrip benar-benar ada di berkas yang sama.
Lihat `test_console_html_sumber.py` untuk alasan lengkapnya.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(
    encoding="utf-8"
)


def _blok_css(selector: str) -> str:
    """Isi satu blok CSS, tanpa spasi — supaya perbandingannya tidak goyah
    karena pembungkusan baris."""
    cocok = re.search(rf"{re.escape(selector)}\s*\{{[^}}]*\}}", HTML, re.S)
    assert cocok is not None, f"blok {selector} tidak ketemu"
    return cocok.group(0).replace(" ", "").replace("\n", "")


# ── badge hasil ─────────────────────────────────────────────────────────────


def test_badge_punya_lebar_tetap():
    """`Unripe` (6 huruf) dan `JK` (2) membuat kolom hasil bergerigi.

    Kolom itu dibaca menurun untuk mencari REJ di antara puluhan baris, dan
    tepi kiri yang rata membuat mata bisa menyusurinya; lebar yang berubah tiap
    baris memaksa membaca satu per satu.
    """
    blok = _blok_css(".tag")
    assert "min-width:" in blok, blok


def test_badge_teksnya_di_tengah():
    """Lebar tetap tanpa perataan tengah cuma memindahkan masalahnya: teks
    pendek menempel di kiri kotak yang lebar."""
    assert "text-align:center" in _blok_css(".tag")


def test_badge_tetap_inline_block():
    """`display:block` akan membuatnya selebar sel tabel, bukan selebar
    isinya — dan `min-width` jadi tidak ada artinya."""
    assert "display:inline-block" in _blok_css(".tag")


# ── kode line ───────────────────────────────────────────────────────────────


def test_line_ditulis_kapital_di_layar():
    """`line-1` → `LINE-1`. Ditangani layar, BUKAN backend: `line_code` itu
    kunci yang dicocokkan ke `machine_id` dan dipakai di jalur berkas
    (`artifacts/line-1`), jadi mengubah nilainya akan memutus pencocokan itu.
    Yang berubah cuma tampilannya.
    """
    assert "kodeLine" in HTML


def test_kapital_lewat_css_bukan_mengubah_data():
    """`text-transform` menjaga nilai aslinya utuh di DOM — yang menyalin
    teksnya tetap mendapat `line-1`, dan tidak ada tempat kedua yang bisa
    melenceng dari backend."""
    assert "text-transform:uppercase" in _blok_css(".kode-line")


def test_judul_modal_foto_ikut_kapital():
    """Judulnya string di dalam atribut `data-judul`, jadi `text-transform`
    tidak menjangkaunya — tanpa `toUpperCase()` di situ, tabel menulis `LINE-1`
    sementara foto yang dibuka dari baris yang sama menulis `line-1`."""
    blok = HTML[HTML.index("data-judul="):][:420]
    assert "toUpperCase()" in blok, blok[:200]
