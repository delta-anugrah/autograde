"""Garis pemicu capture: aritmetika letaknya, tanpa menggambar.

Operator bertanya "di titik mana buahnya difoto?" dan sebelum ini jawabannya
cuma bisa dibaca dari kode. Jawabannya: saat titik TENGAH kotak janjang masuk
ke kotak ROI (`FrameProcessingWorker._is_in_roi`). Karena buah bergerak dari
kanan ke kiri di conveyor, batas yang dilewati lebih dulu adalah sisi KANAN ROI.

Yang diuji di sini letaknya, bukan warnanya — menggambar butuh cv2, dan suite
ini sengaja jalan tanpanya (CLAUDE.md § Tests). Piksel sungguhannya diuji di
`tests/e2e/test_garis_pemicu_render.py`.
"""
from __future__ import annotations

import pytest

from palmgrade.core.config import Settings

STREAM_W, STREAM_H = 1280, 720


def _pipeline(monkeypatch: pytest.MonkeyPatch, roi: tuple[int, int, int, int]):
    x1, y1, x2, y2 = roi
    for key, val in (("ROI_X1", x1), ("ROI_Y1", y1), ("ROI_X2", x2), ("ROI_Y2", y2)):
        monkeypatch.setenv(key, str(val))
    monkeypatch.setenv("STREAM_WIDTH", str(STREAM_W))
    monkeypatch.setenv("STREAM_HEIGHT", str(STREAM_H))

    # Diimpor di dalam fungsi: modulnya menarik cv2 DAN torch (lewat ultralytics)
    # di level atas, sementara tes ini cuma memakai satu method yang murni
    # aritmetika. `importorskip` membuat CI ringan melewatinya alih-alih gagal
    # koleksi.
    #
    # ⚠️ Dua-duanya harus disebut. Dulu cuma `cv2`, dan itu cukup selama CI tidak
    # memasang keduanya. Begitu `opencv-python-headless` masuk (untuk langkah
    # e2e), penjaga cv2 berhenti menahan apa pun dan tes ini gagal di torch --
    # merah di langkah unit, gara-gara perubahan di langkah lain.
    pytest.importorskip("cv2")
    pytest.importorskip("torch")
    from palmgrade.pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline

    class _Registry:
        device = "cpu"
        model = None

    return RealtimeInspectionPipeline(_Registry(), Settings())


def test_roi_penuh_layar_tetap_punya_kotak_yang_sah(monkeypatch):
    """`0,0,0,0` artinya seluruh layar, bukan "tidak ada zona".

    Ini keadaan bawaan dan keadaan PC Lampung saat ditanyakan. Kalau method ini
    menjawab None, garis pemicunya tidak digambar justru di keadaan yang paling
    perlu terlihat: janjang difoto begitu terdeteksi di mana pun, termasuk di
    pinggir frame saat janjangnya belum utuh.
    """
    p = _pipeline(monkeypatch, (0, 0, 0, 0))
    assert p.roi_in_stream_space(STREAM_W, STREAM_H) == (0, 0, STREAM_W, STREAM_H)


def test_roi_yang_dikalibrasi_dipakai_apa_adanya(monkeypatch):
    """ROI ditulis dalam ruang stream — yang dilihat operator, tanpa penskalaan."""
    p = _pipeline(monkeypatch, (100, 100, 1180, 620))
    assert p.roi_in_stream_space(STREAM_W, STREAM_H) == (100, 100, 1180, 620)


def test_roi_terbalik_ditolak_bukan_digambar_terbalik(monkeypatch):
    """X2 < X1 itu salah ketik. Menggambarnya terbalik menyesatkan lebih jauh."""
    p = _pipeline(monkeypatch, (900, 100, 200, 620))
    assert p.roi_in_stream_space(STREAM_W, STREAM_H) is None


def test_hanya_x2_yang_kosong_berarti_sampai_tepi_kanan(monkeypatch):
    """Nol pada X2/Y2 berarti "sampai tepi", bukan nol piksel."""
    p = _pipeline(monkeypatch, (200, 50, 0, 0))
    assert p.roi_in_stream_space(STREAM_W, STREAM_H) == (200, 50, STREAM_W, STREAM_H)


def test_warna_pemicu_biru_dan_beda_dari_hijau_roi():
    """Biru, diminta operator — dan wajib beda dari hijau yang sudah dipakai.

    Hijau sudah jadi kotak ROI sekaligus bbox janjang yang lolos. Garis pemicu
    yang ikut hijau tidak bisa ditunjuk operator tanpa dikira bbox.
    """
    from palmgrade.core.constants import COLOR_ROI, COLOR_TRIGGER

    biru, hijau, merah = COLOR_TRIGGER  # OpenCV memakai urutan BGR
    assert biru > 200, "kanal biru harus dominan"
    assert merah < 100, "warna yang kemerahan akan terbaca seperti REJ"
    assert COLOR_TRIGGER != COLOR_ROI
