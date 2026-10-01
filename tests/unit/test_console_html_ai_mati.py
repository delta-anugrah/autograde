"""Pita AI mati di kartu line console.html (batch 2.1), dua lapis seperti
`test_console_html_alarm.py`:

- invarian teks (selalu jalan): pita digambar saat render pertama DAN tiap
  polling, diterjemahkan di kedua bahasa, di-escape;
- perilaku lewat node dengan KAMUS asli: kalimat yang sungguh dibaca operator
  memuat line, jam, dan tindakan, tanpa kode galat (keputusan user 2026-10-01);
  line sehat, line lama tanpa blok `ai`, dan line OFFLINE tidak menggambar apa pun.
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, fungsi, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")

SEJAK = 1_790_000_000.0          # 21.13 WIB


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    return re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M).group(1)


def _line(ai, *, reachable=True) -> dict:
    return {"line_code": "line-2", "name": "Line 2", "plc": {"reachable": reachable, "ai": ai}}


def _js(nilai) -> str:
    return json.dumps(nilai)


AI_MATI = {"keadaan": "ai_mati", "mati": True, "kode": "AI_MATI", "sejak": SEJAK,
           "umur_detik": 42.0, "ambang_detik": 30}


def test_kartu_line_punya_slot_pita_ai_dan_bingkai_merah():
    fn = fungsi("kartuLine")
    assert '<div class="slot-ai">${pitaAi(l)}</div>' in fn
    assert 'aiMati(l) ? " ai-mati" : ""' in fn


def test_pita_ai_diperbarui_tiap_polling_bukan_cuma_render_pertama():
    assert "perbaruiAi(c, l)" in fungsi("refresh")
    assert "tulisKalauBeda(slot, pitaAi(l))" in fungsi("perbaruiAi")


def test_pita_ai_diterjemahkan_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        assert "aiMatiJudul:" in isi and "aiMatiRinci:" in isi, bahasa


def test_pita_ai_memakai_esc():
    assert fungsi("pitaAi").count("esc(") == 2


def test_gaya_kartu_ai_mati_ada():
    assert re.search(r"\.card\.ai-mati\s*\{[^}]*--danger-fg", HTML)
    assert re.search(r"\.pita-ai\s*\{[^}]*--danger-fg", HTML)


def test_tanpa_suara():
    """Suara alert HOLD (keputusan 2026-09-28): tidak ada yang dibunyikan."""
    blok = fungsi("pitaAi") + fungsi("perbaruiAi") + fungsi("aiMati")
    assert not re.search(r"Audio|\.play\(|speechSynthesis|beep", blok)


@butuh_node
def test_ai_mati_menulis_line_jam_dan_tindakan_tanpa_kode():
    html = jalankan(["jamSinkron", "aiMati", "pitaAi"], f"pitaAi({_js(_line(AI_MATI))}, {SEJAK + 42})")
    assert 'class="pita-ai" role="alert"' in html
    assert "Line 2: AI berhenti memproses" in html
    assert "Sejak 21.13." in html
    assert "panggil teknisi" in html
    assert "AI_MATI" not in html and "Kode" not in html


@butuh_node
def test_hari_lain_ikut_tanggal():
    """Pita yang menyala sejak kemarin (kiosk dibiarkan semalaman) harus bilang
    kemarin, bukan jam yang terbaca seperti tadi pagi."""
    html = jalankan(["jamSinkron", "aiMati", "pitaAi"], f"pitaAi({_js(_line(AI_MATI))}, {SEJAK + 86_400})")
    assert "Sejak 21 Sep 21.13." in html


@butuh_node
def test_bahasa_inggris():
    html = jalankan(["jamSinkron", "aiMati", "pitaAi"], f"pitaAi({_js(_line(AI_MATI))}, {SEJAK + 42})", bahasa="en")
    assert "Line 2: AI stopped processing" in html
    assert "Since 21:13." in html
    assert "AI_MATI" not in html and "Code" not in html


@pytest.mark.parametrize(
    "line",
    [
        _line({"keadaan": "sehat", "mati": False}),
        _line({"keadaan": "kamera_putus", "mati": False}),
        _line({"keadaan": "memulai", "mati": False}),
        _line(None),                                  # line versi lama
        _line(AI_MATI, reachable=False),              # OFFLINE sudah bicara sendiri
        {"line_code": "line-9", "name": "? line-9"},  # line asing tanpa plc
    ],
    ids=["sehat", "kamera-putus", "memulai", "line-lama", "offline", "line-asing"],
)
@butuh_node
def test_selain_ai_mati_tidak_menggambar_apa_pun(line):
    assert jalankan(["jamSinkron", "aiMati", "pitaAi"], f"[aiMati({_js(line)}), pitaAi({_js(line)})]") == [False, ""]
