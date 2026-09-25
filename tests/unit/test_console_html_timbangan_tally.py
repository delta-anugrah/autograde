"""Kotak timbangan di strip "Hari ini", di kanan Rasio Ripe (permintaan 2026-09-25).

Strip itu yang terbaca dari jauh sepanjang shift. Grading sudah di situ; neto
yang ditimbang hari ini belum, padahal itu angka yang dibayar. Dijaga sebagai
teks seperti invarian konsol lain (tidak ada test runner JS).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = (REPO_ROOT / "src" / "palmgrade" / "static" / "console.html").read_text(encoding="utf-8")


def _tally() -> str:
    return HTML.split('<section id="tally">', 1)[1].split("</section>", 1)[0]


def test_kotak_timbangan_di_kanan_rasio_sebelum_tata_letak():
    tally = _tally()
    rasio = tally.index('class="rasio"')
    timbang = tally.index('class="timbang"')
    tata = tally.index('class="tata"')
    assert rasio < timbang < tata


def test_kotak_timbangan_punya_angka_neto_dan_rincian():
    tally = _tally()
    assert 'id="tot-neto"' in tally
    assert 'id="tot-tiket"' in tally


def test_refresh_mengisi_kotak_timbangan_dari_state():
    awal = HTML.find("async function refresh()")
    blok = HTML[awal : HTML.find("\n}\n", awal)]
    assert "isiTallyTimbangan(s.timbangan)" in blok


def test_neto_diformat_seperti_tab_timbangan():
    awal = HTML.find("function isiTallyTimbangan")
    assert awal != -1
    blok = HTML[awal : HTML.find("\n}\n", awal)]
    # Helper `kg()` yang sama dengan tab Timbangan: satu format angka berat.
    assert "kg(tb.neto_kg)" in blok
    # Tanpa tiket: tanda kosong, bukan "0 kg" yang terbaca seperti truk kosong.
    assert "KOSONG" in blok


@pytest.mark.parametrize("kunci", ["labelNetoTimbangan", "timbangTiket", "timbangBelumAda"])
def test_kamus_dua_bahasa(kunci):
    assert len(re.findall(rf"\b{kunci}:", HTML)) >= 2, f"{kunci} tidak ada di kedua bahasa"


def test_css_kotak_timbangan_ada():
    assert "#tally .timbang {" in HTML
