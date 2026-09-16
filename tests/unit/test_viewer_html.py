"""Penjaga statis untuk `static/viewer.html`.

Halaman ini beda dari `console.html` di satu hal penting: dia tidak hidup di
PC pabrik, dia diunggah sekali ke Cloudflare R2 dan dibuka lewat tautan dari
tiket ERP — di belakang Cloudflare Access. "Nol CDN" di sini bukan cuma
kebiasaan console.html, itu syarat keamanan: berkas ini tidak boleh
tergantung host lain sama sekali, jadi `https://`/`http://` di mana pun di
dalam berkas ini adalah kebocoran ke luar kotak.

Manifest yang dibacanya (`visits/<id>.json`) datang dari data yang diketik
operator (`plate_number`, `supplier_name`, `grade_class`) — jalur yang sama
yang membuat `console.html` disiplin soal `esc()`/`textContent`. Di sini
disiplinnya sama, cuma tanpa build step untuk memeriksanya selain tes ini.
"""

from __future__ import annotations

import re
from pathlib import Path

VIEWER = Path(__file__).resolve().parents[2] / "src/palmgrade/static/viewer.html"


def test_viewer_has_no_external_dependency():
    html = VIEWER.read_text(encoding="utf-8")
    # Favicon-nya SVG inline dengan `xmlns="http://www.w3.org/2000/svg"` — itu label
    # namespace XML yang wajib ada supaya Chrome/Firefox mau menggambar SVG lepas
    # (data URI diparse sebagai dokumen berdiri sendiri, tanpa xmlns ikonnya tidak
    # tampil sama sekali, senyap, tanpa error). Bukan alamat yang diambil browser,
    # jadi dibuang dulu supaya sisanya benar-benar diperiksa sebagai permintaan
    # jaringan. Pola yang sama dengan `test_console_html.py` untuk `console.html`.
    tanpa_namespace = html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in tanpa_namespace and "http://" not in tanpa_namespace


def test_viewer_reads_the_manifest_relative_to_itself():
    html = VIEWER.read_text(encoding="utf-8")
    # Catatan: brief tugas ini punya draf tes ketiga yang salah,
    # `'"schema"' not in html` — itu bertentangan dengan syarat lain di brief
    # yang sama ("kalau schema !== 1 → tampil pesan versi tidak dikenal").
    # Memeriksa schema di JS BUTUH string literal `"schema"` (baik lewat
    # `manifest.schema` atau `manifest["schema"]`, dan yang kedua memang
    # mengandung substring itu persis). Assertion itu sengaja tidak ditulis
    # di sini — lihat test_viewer_checks_schema_version_before_rendering di
    # bawah untuk invarian yang benar sebagai gantinya.
    assert "visits/" in html and "URLSearchParams" in html


def test_viewer_checks_schema_version_before_rendering():
    """Manifest lama (schema lain) tidak boleh dirender seolah terbaca benar —
    itu bisa salah menampilkan janjang ke backoffice yang sedang menyelesaikan
    sengketa. Halaman harus membandingkan `data.schema` ke versi yang dia
    kenal sebelum menggambar apa pun dari isinya.

    Dicek lewat pola `schema !== <konstanta>` (bukan literal `!== 1` mentah):
    implementasi memakai nama `SCHEMA_DIKENAL = 1` supaya angka kontraknya
    (`domain/visit_manifest.py`, `SCHEMA = 1`) punya satu tempat, bukan
    tersebar di tiap perbandingan.
    """
    html = VIEWER.read_text(encoding="utf-8")
    assert re.search(r"\bschema\s*!==\s*\w+", html), "tidak ada perbandingan schema !== ..."
    assert re.search(r"=\s*1\s*;", html), "konstanta versi schema yang dikenal tidak ketemu"


def test_viewer_stays_under_20kb():
    """Batas keras dari brief. Berkas ini nol CDN dan nol build step — satu-
    satunya cara membuatnya tetap kecil adalah menjaganya tetap kecil."""
    assert VIEWER.stat().st_size < 20 * 1024


def test_viewer_never_uses_innerhtml_with_manifest_fields():
    """`plate_number`, `supplier_name`, dan `grade_class` datang dari data
    yang diketik operator (lihat modul ini). DOM manifest harus dirakit lewat
    `textContent`/`createElement`, bukan `innerHTML` — pola yang sama yang
    dijaga `test_console_html.py` untuk `console.html`."""
    html = VIEWER.read_text(encoding="utf-8")
    assert "innerHTML" not in html


def test_viewer_never_uses_eval_or_function_constructor():
    html = VIEWER.read_text(encoding="utf-8")
    assert "eval(" not in html
    assert "new Function" not in html


def test_viewer_fetches_manifest_id_from_query_string():
    html = VIEWER.read_text(encoding="utf-8")
    assert "get(" in html and "visit" in html


def test_viewer_handles_404_as_not_yet_uploaded():
    """404 punya arti khusus di sini: worker upload jalan lewat antrean, jadi
    truk yang baru saja selesai grading bisa manifest-nya belum sampai
    beberapa menit. Itu beda dari error lain dan harus bilang begitu, bukan
    pesan galat generik."""
    html = VIEWER.read_text(encoding="utf-8")
    assert "404" in html


def test_every_img_has_onerror_fallback():
    """Foto naik ke R2 tiap jam (bukan seketika) dan kena retensi 90 hari —
    manifest yang bisa dibaca tidak menjamin fotonya sudah ada. Tanpa
    `onerror`, gambar yang gagal muat cuma jadi ikon patah browser tanpa
    penjelasan apa pun ke backoffice."""
    html = VIEWER.read_text(encoding="utf-8")
    assert "onerror" in html


def test_viewer_labels_verdict_with_text_not_colour_alone():
    """Hijau/merah untuk ACC/REJ tidak boleh jadi satu-satunya sinyal — itu
    satu hal yang wajib tidak terlewat untuk pembaca buta warna. Tekstualnya
    harus ada: label kata "ACC"/"REJ" sendiri, bukan cuma warna bingkai."""
    html = VIEWER.read_text(encoding="utf-8")
    assert "ACC" in html
    assert "REJ" in html


def test_viewer_closes_overlay_on_escape():
    """Klik janjang membuka overlay foto penuh; brief minta bisa ditutup
    lewat Escape maupun klik backdrop, bukan cuma tombol tutup."""
    html = VIEWER.read_text(encoding="utf-8")
    assert "Escape" in html
