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


def test_label_strip_hari_ini_data_timbangan():
    """Permintaan operator 2026-09-29: "Neto Timbangan" jadi "Data Timbangan".
    Kepala tabel "Neto (kg)" tidak ikut berubah."""
    assert 'labelNetoTimbangan:"Data timbangan"' in HTML
    assert 'labelNetoTimbangan:"Weighing data"' in HTML
    assert '<span class="lb" data-t="labelNetoTimbangan">Data timbangan</span>' in HTML
    assert "Neto timbangan" not in HTML and "Weighed net" not in HTML


# ── Timbangan live (2026-10-06) ─────────────────────────────────────────────


def test_angka_besar_adalah_berat_live_dan_neto_hari_ini_di_baris_kecil():
    tally = _tally()
    kotak = tally[tally.index('class="timbang"') :]
    assert kotak.index('id="timbang-kg"') < kotak.index('class="timbang-sub"') < kotak.index('id="tot-neto"')
    assert 'id="timbang-keadaan"' in kotak


def test_live_dipolling_tiap_detik_di_semua_tab():
    awal = HTML.rindex("(async () => {")
    blok = HTML[awal:]
    assert "setInterval(sekaliJalan(muatTimbanganLive), 1000)" in blok


def test_render_live_tanpa_hitungan_di_layar():
    awal = HTML.find("function gambarTimbanganLive")
    blok = HTML[awal : HTML.find("\n}\n", awal)]
    # Angka dan keadaan dari server; layar cuma memformat (L4, F3).
    assert "kg(r.kg)" in blok
    assert "KOSONG" in blok
    # Keadaan asing tidak pernah masuk ke atribut: dibaca putus.
    assert ': "putus"' in blok


@pytest.mark.parametrize(
    "kunci",
    ["timbangHariIni", "timbangTidakDipakai", "timbangMemeriksa", "timbangPutus",
     "timbangError", "timbangStabil", "timbangBergerak", "timbangTerbaca"],
)
def test_kamus_live_dua_bahasa(kunci):
    assert len(re.findall(rf"\b{kunci}:", HTML)) >= 2, f"{kunci} tidak ada di kedua bahasa"


def test_belum_dipasang_tertulis_belum_tersambung():
    assert 'timbangTidakDipakai:"Belum tersambung"' in HTML
    assert 'timbangTidakDipakai:"Not connected"' in HTML
