"""Setelan Kamera cards (tab Line), rendered through node with the real KAMUS."""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
FUNGSI = ["kunciSebabTakTerbaca", "angkaSetelan", "nilaiSetelanKamera", "rentangSetelanKamera", "kartuSetelanKamera"]
LAMPUNG = {
    "terjangkau": True, "berkas_tersimpan": False, "berkas_fitur": "models/01102026.mfs",
    "setelan": [
        {"kunci": "exposure", "node": "ExposureTime", "jenis": "float", "satuan": "µs", "bisa_diubah": True,
         "didukung": True, "nilai": 4000.0, "min": 15.0, "max": 9959540.0, "langkah": None, "pilihan": []},
        {"kunci": "white_balance", "node": "BalanceWhiteAuto", "jenis": "enum", "satuan": "", "bisa_diubah": True,
         "didukung": True, "nilai": "Continuous", "min": None, "max": None, "langkah": None,
         "pilihan": ["Off", "Once", "Continuous"]},
        {"kunci": "gain_auto", "node": "GainAuto", "jenis": "enum", "satuan": "", "bisa_diubah": False,
         "didukung": False, "nilai": None, "min": None, "max": None, "langkah": None, "pilihan": []},
    ],
}


def _kartu(d: dict, bahasa: str = "id") -> str:
    return jalankan(FUNGSI, f"kartuSetelanKamera('line-1', {json.dumps(d)})", bahasa=bahasa)


def _baris(html: str, label: str) -> str:
    cocok = re.search(rf"<dt>{re.escape(label)}</dt><dd>(.*?)</dd>", html)
    assert cocok, (label, html)
    return cocok.group(1)


@butuh_node
def test_nilai_dan_rentang_kamera_lampung():
    html = _kartu(LAMPUNG)
    assert _baris(html, "Exposure") == '4.000 µs <span class="muted">(15 sampai 9.959.540)</span>'
    assert _baris(html, "White balance") == "Continuous"


@butuh_node
def test_node_tidak_didukung_disebut_bukan_kosong():
    assert _baris(_kartu(LAMPUNG), "Gain otomatis") == "tidak didukung kamera ini"


@butuh_node
def test_sumber_setelan_tanpa_nama_berkas():
    """F6: the file name stays off the screen; the card only says saved or baseline."""
    html = _kartu(LAMPUNG)
    assert "01102026" not in html
    assert "Setelan bawaan" in html
    assert "Tersimpan dari konsol" in _kartu({**LAMPUNG, "berkas_tersimpan": True})


@butuh_node
def test_line_bukan_hikrobot_dan_kamera_diam():
    assert "bukan kamera Hikrobot" in _kartu({"terjangkau": False, "sebab_kode": "bukan_kamera"})
    assert "Kamera tidak menjawab" in _kartu({"terjangkau": False, "sebab_kode": "kamera_tidak_menjawab"})


@butuh_node
def test_line_mati_memakai_kalimat_line_yang_sudah_ada():
    html = _kartu({"terjangkau": False, "sebab_kode": "tak_terjangkau"})
    assert "Line tidak menjawab sama sekali" in html


@butuh_node
def test_teks_dari_line_di_escape():
    jahat = {**LAMPUNG, "setelan": [{**LAMPUNG["setelan"][1], "nilai": "<img src=x onerror=alert(1)>"}]}
    assert "<img" not in _kartu(jahat)


@butuh_node
def test_bahasa_inggris():
    html = _kartu(LAMPUNG, bahasa="en")
    assert _baris(html, "Exposure") == '4,000 µs <span class="muted">(15 to 9,959,540)</span>'
    assert _baris(html, "Gain auto") == "not supported by this camera"


def test_sub_pilihan_ada_di_tab_line():
    assert 'data-sub="setelan-kamera"' in HTML
    assert '"setelan-kamera": muatSetelanKamera' in HTML
