"""Foto janjang dibuka di tempat, bukan di tab baru.

Dulu `target="_blank"`: tiap foto yang dilihat meninggalkan satu tab, dan di
kiosk Chrome (`--kiosk`, `scripts/console-kiosk.sh`) tab baru tidak punya bar
alamat maupun tombol tutup — operator kehilangan layarnya sendiri dan tidak
punya cara jelas untuk kembali.

Invarian teks atas `console.html`, seperti `test_console_html.py`: tidak ada
runner JS di repo ini, jadi yang dikunci adalah bentuk sumbernya. Perilaku
runtime-nya (buka, Esc, klik backdrop, `src` dilepas) dibuktikan lawan konsol
sungguhan di browser.

Ini BUKAN pelanggaran § Critical Rules 20 (dialog tara yang ditolak operator):
yang itu menutup kamera line justru saat operator sedang butuh melihatnya. Di
sini menutup layar memang yang diminta — melihat foto lebih besar, sebentar,
lalu kembali.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

KONSOL = Path(__file__).resolve().parents[2] / "src" / "palmgrade" / "static" / "console.html"


@pytest.fixture(scope="module")
def html() -> str:
    return KONSOL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kode(html: str) -> str:
    """`console.html` tanpa komentar HTML.

    Komentar di berkas ini panjang dan menjelaskan apa yang DIHINDARI — termasuk
    menyebut `target="_blank"` dan `https://` apa adanya. Mencari string itu di
    seluruh berkas akan menangkap penjelasannya, bukan kodenya.
    """
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


def test_tidak_ada_lagi_tautan_yang_membuka_tab_baru(kode):
    """Yang sebenarnya diminta. Satu `target="_blank"` yang lolos berarti kiosk
    kehilangan layarnya lagi."""
    assert 'target="_blank"' not in kode


def test_pemicunya_tombol_bukan_tautan(html):
    """`<a>` tanpa href yang berguna adalah tautan bohong: pembaca layar
    mengumumkannya sebagai navigasi, dan klik-tengah/`Buka di tab baru` pada
    menu konteks menghasilkan halaman kosong."""
    assert 'class="foto" data-foto=' in html
    assert re.search(r'<button type="button" class="foto"', html)


def test_dialog_bawaan_bukan_lapisan_buatan_sendiri(html):
    """`<dialog>` memberi Esc, fokus terkunci, dan sisa halaman disembunyikan
    dari pembaca layar tanpa satu baris JS pun."""
    assert '<dialog id="foto-modal"' in html
    assert "showModal()" in html


def test_src_diisi_saat_dibuka_bukan_saat_baris_digambar(html):
    """25 baris per halaman berarti 25 foto penuh berukuran megabyte yang tidak
    pernah dilihat siapa pun kalau `src` diisi lebih awal."""
    assert 'data-foto="' in html
    assert '$("foto-besar").src = tombol.dataset.foto' in html
    # Thumbnail di tabel tetap dimuat malas.
    assert 'loading="lazy"' in html


def test_src_dilepas_setelah_ditutup(html):
    """Foto janjang 1920x1080+ tidak boleh menetap di memori sepanjang shift."""
    blok = html.split('$("foto-modal").addEventListener("close"')[1][:200]
    assert 'removeAttribute("src")' in blok


def test_klik_backdrop_menutup_tapi_klik_gambar_tidak(html):
    """`<dialog>` menganggap backdrop bagian dari dirinya, jadi tanpa
    perbandingan target ini klik pada gambarnya sendiri ikut menutup."""
    blok = html.split('$("foto-modal").addEventListener("click"')[1][:260]
    assert "ev.target === ev.currentTarget" in blok


def test_listener_didelegasikan_bukan_per_baris(html):
    """Tabel grading digambar ulang tiap perpindahan halaman dan tiap polling 2
    detik; listener per <img> akan hilang bersama barisnya."""
    blok = [
        b for b in html.split('document.addEventListener("click"')[1:]
        if "button.foto" in b[:300]
    ]
    assert blok, "listener foto bukan di document — akan hilang saat tabel digambar ulang"
    assert 'closest("button.foto")' in blok[0][:300]


def test_tombol_tutup_cukup_besar_untuk_jempol_bersarung(html):
    """Layar sentuh, luar ruangan. Aturan yang sama dipakai tombol lain di sini."""
    css = html.split("#foto-tutup")[1][:220]
    assert "min-width:44px" in css and "min-height:44px" in css


def test_lebar_gambar_relatif_ke_dialog_bukan_ke_layar(html):
    """Regresi: gambarnya sempat `max-width:96vw` sementara dialognya dibatasi
    `min(96vw, 1100px)`. Di layar lebih lebar dari 1100px gambar jadi lebih besar
    daripada wadahnya, dan `overflow:hidden` memotong sisi kanannya — tanpa
    scrollbar apa pun sebagai petunjuk bahwa ada bagian foto yang hilang.

    `width:100%` mengikat gambar ke lebar dialog, berapa pun lebar layarnya."""
    css = html.split("#foto-besar")[1][:320]
    assert "width:100%" in css
    assert "96vw" not in css, "satuan viewport di sini = kepotong lagi di layar lebar"
    # Tinggi TETAP dipatok ke viewport dikurangi baris judul: foto potret yang
    # lebih tinggi dari layar akan mendorong tombol tutup keluar jangkauan.
    assert "max-height:calc(92vh" in css
    assert "object-fit:contain" in css, "cover akan memangkas isi foto"


def test_masih_nol_referensi_https(kode):
    """Aturan lama: konsol harus jalan saat internet putus. Modal ini sengaja
    tidak memakai pustaka apa pun."""
    assert "https://" not in kode
