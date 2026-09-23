"""Invarian HTML layar Setelan dan Versi — dijaga sebagai teks, seperti tetangganya.

Konsol tidak punya test runner JS, jadi yang bisa dijaga di CI adalah bahwa
elemen, kelas, dan kunci i18n yang dipakai skrip benar-benar ada di berkas yang
sama. Lihat `test_console_html_sumber.py` untuk alasan lengkapnya.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(encoding="utf-8")


# ── Setelan: accordion ──────────────────────────────────────────────────────


def test_setelan_dibagi_tiga_kelompok():
    """Tiga `<details>`: Grading, Kamera & Conveyor, Mode Dev."""
    for kunci in ("grading", "kamera", "dev"):
        assert f'data-setelan-grup="{kunci}"' in HTML


def test_kelompok_pertama_terbuka_awal():
    """Layar yang semua bagiannya tertutup terbaca seperti layar kosong."""
    cocok = re.search(r'<details[^>]*data-setelan-grup="grading"[^>]*>', HTML)
    assert cocok is not None
    assert " open" in cocok.group(0)


def test_kelompok_lain_tertutup_awal():
    for kunci in ("kamera", "dev"):
        cocok = re.search(rf'<details[^>]*data-setelan-grup="{kunci}"[^>]*>', HTML)
        assert cocok is not None, kunci
        assert " open" not in cocok.group(0), kunci


def test_tiap_kelompok_punya_ringkasan_berlabel():
    """`<summary>` tanpa `data-t` tidak ikut berganti bahasa."""
    for kunci in ("grading", "kamera", "dev"):
        blok = re.search(
            rf'<details[^>]*data-setelan-grup="{kunci}".*?</summary>', HTML, re.S
        )
        assert blok is not None, kunci
        assert "data-t=" in blok.group(0), kunci


def test_semua_kolom_lama_masih_ada():
    """Merapikan tampilan tidak boleh menghilangkan satu pun kolom."""
    for el in ("set-conf", "set-minsize", "set-sumbu", "set-garis", "set-dev"):
        assert f'id="{el}"' in HTML, el


def test_tombol_simpan_di_luar_kelompok():
    """Simpan menyimpan SEMUA kelompok, jadi tidak boleh bersembunyi di dalam
    salah satunya — tertutup accordion berarti tidak bisa ditekan."""
    posisi_simpan = HTML.index('id="set-simpan"')
    penutup_terakhir = HTML.rindex("</details>", 0, posisi_simpan)
    assert penutup_terakhir < posisi_simpan


def test_setelan_form_tidak_dipatok_sempit():
    """`max-width:30rem` membuat layar 1900 px terpakai sepertiga."""
    cocok = re.search(r"\.setelan-form\s*\{[^}]*\}", HTML, re.S)
    assert cocok is not None
    assert "max-width:30rem" not in cocok.group(0).replace(" ", "")


# ── Versi ───────────────────────────────────────────────────────────────────


def test_daftar_definisi_tidak_dipatok_480px():
    cocok = re.search(r"\.daftar-definisi\s*\{[^}]*\}", HTML, re.S)
    assert cocok is not None
    assert "max-width:480px" not in cocok.group(0).replace(" ", "")


def test_versi_dev_punya_kunci_i18n_di_dua_bahasa():
    """Dua kamus. Kunci yang cuma ada di satu membuat layar menampilkan nama
    kunci mentah saat bahasa lain dipilih."""
    assert HTML.count("versiDariSource:") == 2


def test_versi_dev_tidak_menulis_unknown_mentah():
    """`unknown` terbaca seperti kerusakan; yang benar 'dev (dari source)'."""
    assert "versiDariSource" in HTML
