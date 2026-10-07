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


def test_kotak_timbangan_di_kanan_rasio_tata_letak_di_kepala():
    tally = _tally()
    assert tally.index('id="tot-rate"') < tally.index('id="timbang"')
    kepala = HTML.split('<header id="topbar">', 1)[1].split("</header>", 1)[0]
    assert 'class="tata"' in kepala


def test_neto_hari_ini_dan_rincian_di_tampilan_timbangan():
    # 2026-10-07 (spec §2.3): neto of the day left the Grading view; the live weight stayed.
    timbangan = HTML.split('<section id="sec-timbangan"', 1)[1].split("</section>", 1)[0]
    assert 'id="tot-neto"' in timbangan
    assert 'id="tot-tiket"' in timbangan


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


@pytest.mark.parametrize("kunci", ["labelTimbangSekarang", "timbangTiket", "timbangBelumAda"])
def test_kamus_dua_bahasa(kunci):
    assert len(re.findall(rf"\b{kunci}:", HTML)) >= 2, f"{kunci} tidak ada di kedua bahasa"


def test_css_kotak_timbangan_ada():
    assert "  #timbang {" in HTML


def test_label_kotak_timbangan_sekarang():
    """2026-10-07: the card shows the scale now; "Data timbangan" (2026-09-29) went with the
    neto line to the Timbangan view."""
    assert '<span class="lb" data-t="labelTimbangSekarang">Timbangan sekarang</span>' in _tally()
    assert "labelNetoTimbangan" not in HTML
    assert "Neto timbangan" not in HTML and "Weighed net" not in HTML


# ── Timbangan live (2026-10-06) ─────────────────────────────────────────────


def test_angka_besar_adalah_berat_live_dengan_jejak_dan_saran():
    tally = _tally()
    kotak = tally[tally.index('id="timbang"') :]
    assert kotak.index('id="timbang-keadaan"') < kotak.index('id="timbang-kg"') < kotak.index('id="timbang-jejak"')
    assert kotak.index('id="timbang-jejak"') < kotak.index('id="timbang-saran"')
    assert 'id="tot-neto"' not in kotak


def test_live_dipolling_tiap_detik_di_semua_tab():
    awal = HTML.rindex("(async () => {")
    blok = HTML[awal:]
    assert "setInterval(sekaliJalan(muatTimbanganLive), 1000)" in blok


def test_render_live_tanpa_hitungan_di_layar():
    awal = HTML.find("function gambarTimbanganLive")
    blok = HTML[awal : HTML.find("\n}\n", awal)]
    # Angka dan keadaan dari server; layar cuma memformat (L4, F3).
    assert 'tulisBerat($("timbang-kg")' in blok
    assert "SARAN_TIMBANG[keadaan]" in blok
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
