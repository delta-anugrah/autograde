"""Invarian HTML layar Rekam Video — dijaga sebagai teks, seperti tetangganya.

Konsol tidak punya test runner JS, jadi yang bisa dijaga di CI adalah bahwa
elemen, kunci i18n, dan endpoint yang dipakai skrip benar-benar ada di berkas
yang sama. Itu menangkap kesalahan yang paling sering: rute diganti namanya di
Python dan HTML-nya tertinggal.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(
    encoding="utf-8"
)


def test_tab_rekam_ada_dan_ditandai_dev():
    assert 'data-tab="rekam"' in HTML
    baris = [b for b in HTML.splitlines() if 'data-tab="rekam"' in b][0]
    # `data-dev="1"` yang membuat tab ini hilang untuk operator. Kerapian, bukan
    # pengaman — backend yang menolak — tapi tanpa itu operator melihat menu
    # yang selalu dijawab 403.
    assert 'data-dev="1"' in baris


def test_panel_rekam_ada():
    assert 'id="sec-rekam"' in HTML


def test_endpoint_rekam_dipanggil():
    assert "/api/console/dev/rekam" in HTML


def test_kunci_i18n_ada_di_dua_bahasa():
    """Dua kamus. Kunci yang cuma ada di satu membuat layar menampilkan nama
    kunci mentah saat bahasa lain dipilih."""
    for kunci in (
        "judulRekamVideo",
        "rekamMulai",
        "rekamStop",
        "rekamSedangMerekam",
        "rekamMati",
        "rekamTakTerbaca",
        "rekamDiskBebas",
        "rekamSetelanJudul",
        "rekamSimpanSetelan",
        "rekamCatatanRetensi",
    ):
        assert HTML.count(f"{kunci}:") == 2, kunci


def test_empat_kolom_setelan_ada():
    for el in ("rekam-width", "rekam-height", "rekam-fps", "rekam-bitrate"):
        assert f'id="{el}"' in HTML, el


def test_peringatan_retensi_manual_disebut():
    """Rekaman TIDAK dihapus otomatis. Support yang tidak tahu itu akan
    meninggalkannya menumpuk sampai disk pabrik penuh."""
    assert "rekamCatatanRetensi" in HTML


def test_tidak_ada_referensi_https():
    """Konsol harus hidup saat internet putus — nol referensi https://."""
    assert "https://" not in HTML


def test_polling_berhenti_saat_tab_ditutup():
    """Polling yang jalan terus di tab lain membebani tiga line tanpa guna."""
    assert re.search(r"rekamTimer|hentikanPollingRekam", HTML) is not None


def test_setelan_dikirim_sebagai_string_json():
    """`api()` meneruskan opts ke fetch apa adanya, jadi body WAJIB string.

    Objek telanjang dikirim sebagai "[object Object]" dan dijawab 422. Gejalanya
    menyesatkan: toast merah memang muncul, tapi bunyinya "gagal menyimpan"
    sementara penyebabnya bentuk payload — dan setelan diam-diam tetap lama.
    Ketemu di browser 2026-09-22.
    """
    blok = HTML[HTML.index('"/api/console/dev/rekam/setelan"'):][:600]
    assert "JSON.stringify" in blok


def test_tombol_menunjukkan_sedang_bekerja():
    """Stop menahan ~2 detik (line menunggu encoder menutup berkas). Tanpa
    tulisan yang berubah, jeda itu terbaca seperti tombol yang tidak bereaksi."""
    assert HTML.count("rekamMenunggu:") == 2
    assert 'el.textContent = t("rekamMenunggu")' in HTML
