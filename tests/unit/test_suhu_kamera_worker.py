"""`FrameCaptureWorker` membaca suhu kamera tiap 10 detik, bukan tiap frame.

15 fps x 3 line = 45 panggilan SDK per detik kalau dibaca tiap frame, untuk angka
yang berubah dalam hitungan menit.
"""
from __future__ import annotations

import logging

from ai_palsu import LinePalsu

from palmgrade.workers import frame_capture_worker


def test_suhu_tersimpan_dengan_jamnya():
    line = LinePalsu()
    line.kamera.suhu = 47.3
    line.jalan(1)
    assert line.state.suhu_kamera_c == 47.3
    assert line.state.suhu_kamera_at == 1_000.0


def test_dibaca_tiap_sepuluh_detik_bukan_tiap_frame():
    line = LinePalsu()
    line.kamera.suhu = 47.3
    line.jalan(25)                     # frame di detik 0..24
    assert frame_capture_worker.SUHU_JEDA_DETIK == 10.0
    assert line.kamera.suhu_dibaca == 3  # detik 0, 10, 20


def test_sumber_tanpa_sensor_tidak_pernah_mengisi_suhu(caplog):
    line = LinePalsu()
    with caplog.at_level(logging.WARNING):
        line.jalan(25)
    assert line.state.suhu_kamera_c is None
    assert not [r for r in caplog.records if "temperature" in r.getMessage().lower()]


def test_tidak_ditanya_saat_gambar_tidak_mengalir():
    line = LinePalsu()
    line.kamera.suhu = 47.3
    line.kamera.mengirim = False
    line.jalan(12, deteksi=False)          # tiap putaran gagal tidur 0,1 dtk sungguhan
    assert line.kamera.suhu_dibaca == 0


def test_galat_sdk_tidak_menjatuhkan_capture(caplog):
    line = LinePalsu()
    line.kamera.suhu_melempar = True
    with caplog.at_level(logging.DEBUG, logger=frame_capture_worker.logger.name):
        line.jalan(25)
    assert line.state.suhu_kamera_c is None
    assert line.state.frame_terakhir_at == 1_024.0      # frame tetap masuk sampai akhir
    galat = [r.levelno for r in caplog.records if "temperature" in r.getMessage().lower()]
    assert galat == [logging.WARNING, logging.DEBUG, logging.DEBUG]
