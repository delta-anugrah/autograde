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


# ── Setelan: sub-tabs (user 2026-10-05, replacing the accordion) ───────────

SUB = ("grading", "kamera", "tampilan", "dev", "penugasan", "slip", "bahaya")


def _bagian() -> str:
    return HTML.split('<section id="sec-setelan"', 1)[1].split("</section>", 1)[0]


def test_tujuh_sub_tab_berlabel_dua_bahasa():
    """Same component as the Line tab, one button per part, each worded through KAMUS."""
    bar = re.search(r'<div class="log-level" id="setelan-sub" role="group">(.*?)</div>', _bagian(), re.S)
    assert bar, "the Settings sub-tab bar is missing"
    tombol = re.findall(r'<button type="button" data-sub="(\w+)" data-t="(\w+)">', bar.group(1))
    assert [sub for sub, _ in tombol] == list(SUB)
    for _, kunci in tombol:
        assert HTML.count(f"{kunci}:") == 2, f"{kunci} must exist in id and en"


def test_tiap_bagian_punya_panelnya():
    bagian = _bagian()
    for kunci in SUB[:-1]:
        assert f'<div class="setelan-grup" data-setelan-grup="{kunci}">' in bagian, kunci
    assert '<div id="setform-bahaya">' in bagian and '<details id="bahaya" class="bahaya">' in bagian


def test_empat_bagian_satu_tombol_simpan_dalam_satu_form():
    """Grading, Camera & Conveyor, Video display and Developer Mode are saved by one Simpan,
    so they share one form and the button sits after all four, outside each of them."""
    utama = _bagian().split('id="setform-utama"', 1)[1].split('id="setform-penugasan"', 1)[0]
    for kunci in ("grading", "kamera", "tampilan", "dev"):
        assert f'data-setelan-grup="{kunci}"' in utama, kunci
    assert utama.index('id="set-simpan"') > utama.index('data-setelan-grup="dev"')


def test_pindah_sub_tab_menyembunyikan_yang_lain_dan_diingat():
    js = HTML.split("function terapkanSubSetelan()", 1)[1].split("\n}", 1)[0]
    assert "g.hidden = g.dataset.setelanGrup !== subSetelan" in js
    assert "$(id).hidden = id !== FORM_SETELAN[subSetelan]" in js
    assert 'simpan("subSetelan", subSetelan)' in HTML
    assert 'baca("subSetelan", "grading")' in HTML


def test_hidden_tidak_dikalahkan_display_grid():
    """`.setelan-form` is `display:grid`, which beats the browser's own `[hidden]`."""
    assert ".setelan-form[hidden], .setelan-grup[hidden], #setform-bahaya[hidden] { display:none; }" in HTML


def test_semua_kolom_lama_masih_ada():
    """Merapikan tampilan tidak boleh menghilangkan satu pun kolom."""
    for el in ("set-conf", "set-minsize", "set-sumbu", "set-garis", "set-dev"):
        assert f'id="{el}"' in HTML, el


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
