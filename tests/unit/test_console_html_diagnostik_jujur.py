"""Kartu Diagnostik jujur (batch 3.6 / 3.7), dirender lewat node dengan KAMUS asli.

Janji `docs/MANUAL.md`: kartu memuat kamera, fps, GPU, PLC per line; PLC ✓
hanya kalau benar tersambung; `capture_save_dropped` dan `tp_telat` harus nol.
"""
from __future__ import annotations

import json
import re

import pytest
from konsol_js import HTML, NODE, jalankan

butuh_node = pytest.mark.skipif(NODE is None, reason="node tidak ada")
FUNGSI = ["tanda", "diagPlc", "diagAngka", "diagFrame", "diagDisk", "diagLisensi", "diagNol", "diagSuhu", "kartuDiagnostik"]
TAMBAHAN = 'const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));'

SEHAT = {
    "terjangkau": True, "camera_connected": True, "gpu_available": True, "gpu_device": "RTX 3060",
    "plc": {"connected": True, "inputs": []}, "workers": [{"name": "capture", "alive": True}],
    "outbox_pending": 0, "outbox_failed": 0, "capture_save_dropped": 0, "tp_telat": 0,
    "version": "v1.20.0", "model_file": "best.pt", "model_backend": "tensorrt",
    "fps_kamera": 14.94, "fps_deteksi": 7.2, "frame_umur_detik": 0.1, "suhu_kamera_c": 47.3,
    "ai": {"keadaan": "sehat"},
    "disk": {"tingkat": "aman", "bebas_gb": 232.0, "persen_bebas": 49.6},
    "lisensi": {"aktif": True, "grading_diblokir": False, "berlaku_sampai": 1_822_000_000},
}


def _kartu(d: dict, bahasa: str = "id") -> str:
    return jalankan(FUNGSI, f"kartuDiagnostik('line-1', {json.dumps(d)})", bahasa=bahasa, tambahan=TAMBAHAN)


def _baris(html: str, label: str) -> str:
    cocok = re.search(rf"<dt>{re.escape(label)}</dt><dd>(.*?)</dd>", html)
    assert cocok, (label, html)
    return cocok.group(1)


@butuh_node
def test_line_sehat_semua_baris_baru_terbaca():
    html = _kartu(SEHAT)
    assert _baris(html, "FPS kamera / deteksi") == "14,9 / 7,2"
    assert _baris(html, "Gambar terakhir") == "0,1 dtk lalu"
    assert _baris(html, "Disk") == '<span class="tanda-ok">232 GB bebas (49,6%)</span>'
    assert "tanda-ok" in _baris(html, "PLC")
    assert "tanda-ok" in _baris(html, "Lisensi")
    assert _baris(html, "Versi / model") == "v1.20.0 · best.pt (tensorrt)"
    assert _baris(html, "Janjang tak tersimpan") == '<span class="tanda-ok">0</span>'
    assert _baris(html, "TP telat") == '<span class="tanda-ok">0</span>'
    assert "tanda-gagal" not in html


@butuh_node
def test_plc_menyala_tapi_terputus_silang_merah():
    html = _kartu({**SEHAT, "plc": {"connected": False, "inputs": []}})
    assert "tanda-gagal" in _baris(html, "PLC")


@butuh_node
def test_plc_line_lama_tanpa_connected_tidak_diketahui_bukan_centang():
    html = _kartu({**SEHAT, "plc": {"inputs": []}})
    assert _baris(html, "PLC") == "tidak diketahui (line versi lama)"


@butuh_node
def test_frame_berhenti_umur_gambar_merah_dan_fps_nol():
    d = {**SEHAT, "fps_kamera": 0.0, "fps_deteksi": 0.0, "frame_umur_detik": 42.0,
         "ai": {"keadaan": "frame_berhenti"}}
    html = _kartu(d)
    assert _baris(html, "FPS kamera / deteksi") == "0 / 0"
    assert _baris(html, "Gambar terakhir") == '<span class="tanda-gagal">42 dtk lalu</span>'


@butuh_node
def test_disk_peringatan_kuning_kritis_merah():
    kuning = _kartu({**SEHAT, "disk": {"tingkat": "peringatan", "bebas_gb": 12.3, "persen_bebas": 2.6}})
    merah = _kartu({**SEHAT, "disk": {"tingkat": "kritis", "bebas_gb": 3.0, "persen_bebas": 0.6}})
    assert _baris(kuning, "Disk") == '<span class="tanda-waspada">12,3 GB bebas (2,6%)</span>'
    assert 'class="tanda-gagal"' in _baris(merah, "Disk")


@butuh_node
def test_angka_yang_wajib_nol_merah_di_atas_nol():
    html = _kartu({**SEHAT, "capture_save_dropped": 3, "tp_telat": 1})
    assert _baris(html, "Janjang tak tersimpan") == '<span class="tanda-gagal">3</span>'
    assert _baris(html, "TP telat") == '<span class="tanda-gagal">1</span>'


@butuh_node
def test_lisensi_diblokir_silang_dan_mati_strip():
    diblokir = _kartu({**SEHAT, "lisensi": {"aktif": True, "grading_diblokir": True}})
    mati = _kartu({**SEHAT, "lisensi": {"aktif": False, "grading_diblokir": False}})
    assert "tanda-gagal" in _baris(diblokir, "Lisensi")
    assert _baris(mati, "Lisensi") == "-"


@butuh_node
def test_line_versi_lama_tanpa_field_baru_tetap_terbaca():
    lama = {k: v for k, v in SEHAT.items()
            if k not in ("fps_kamera", "fps_deteksi", "frame_umur_detik", "disk", "lisensi",
                         "capture_save_dropped", "tp_telat")}
    html = _kartu(lama)
    for label in ("Gambar terakhir", "Disk", "Lisensi", "Janjang tak tersimpan", "TP telat"):
        assert _baris(html, label) == "-", label
    assert _baris(html, "FPS kamera / deteksi") == "- / -"


@butuh_node
def test_bahasa_inggris():
    html = _kartu(SEHAT, bahasa="en")
    assert _baris(html, "Last image") == "0.1 s ago"
    assert _baris(html, "Disk") == '<span class="tanda-ok">232 GB free (49.6%)</span>'


def test_tanda_waspada_memakai_token_tema():
    assert re.search(r"\.tanda-waspada\s*\{[^}]*color:var\(--warn\)", HTML)


@butuh_node
def test_suhu_kamera_terbaca():
    assert _baris(_kartu(SEHAT), "Suhu kamera") == "47,3 °C"
    assert _baris(_kartu(SEHAT, bahasa="en"), "Camera temperature") == "47.3 °C"


@butuh_node
def test_suhu_tidak_tahu_strip():
    assert _baris(_kartu({**SEHAT, "suhu_kamera_c": None}), "Suhu kamera") == "-"


@butuh_node
def test_line_versi_lama_tanpa_suhu_strip():
    lama = {k: v for k, v in SEHAT.items() if k != "suhu_kamera_c"}
    assert _baris(_kartu(lama), "Suhu kamera") == "-"


@butuh_node
def test_suhu_belum_berwarna():
    """Batas aman belum diputuskan: tidak ada hijau/kuning/merah di baris ini."""
    assert "tanda-" not in _baris(_kartu({**SEHAT, "suhu_kamera_c": 71.0}), "Suhu kamera")
