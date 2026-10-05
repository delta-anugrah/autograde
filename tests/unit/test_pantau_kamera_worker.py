"""`FrameCaptureWorker` watches the camera every 10 s: rate held low, frames lost, disconnects.

`LinePalsu` hands one frame per fake second, so the measured rate is 1 fps; the camera's own
target (`camera_fps_terukur`) is set per test to make that rate normal or low.
"""
from __future__ import annotations

import logging

from ai_palsu import LinePalsu

from palmgrade.domain.kesehatan_kamera import StatistikAliran
from palmgrade.workers import frame_capture_worker


def _log(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == frame_capture_worker.logger.name]


def test_jedanya_sepuluh_detik():
    assert frame_capture_worker.PANTAU_KAMERA_JEDA_DETIK == 10.0


def test_laju_normal_tidak_ditandai(caplog):
    line = LinePalsu()
    line.state.camera_fps_terukur = 1.0
    with caplog.at_level(logging.INFO):
        line.jalan(300)
    assert line.state.laju_kamera.turun is False
    assert not [m for m in _log(caplog) if "Laju kamera" in m]


def test_laju_rendah_bertahan_satu_warning_lalu_satu_pulih(caplog):
    line = LinePalsu()
    line.state.camera_fps_terukur = 2.0          # 1 fps measured, below 90 % of 2
    with caplog.at_level(logging.INFO, logger=frame_capture_worker.logger.name):
        line.jalan(300)
        assert line.state.laju_kamera.turun is True
        line.state.camera_fps_terukur = 1.0      # back to normal
        line.jalan(120)
    assert line.state.laju_kamera.turun is False
    laju = [r for r in caplog.records if "Laju kamera" in r.getMessage()]
    assert [r.levelno for r in laju] == [logging.WARNING, logging.WARNING]
    assert "turun" in laju[0].getMessage() and "normal lagi" in laju[1].getMessage()


def test_frame_hilang_masuk_jendela(caplog):
    line = LinePalsu()
    line.kamera.statistik = StatistikAliran(diterima=0, hilang=0)
    line.jalan(10)                                       # baseline at second 0
    line.kamera.statistik = StatistikAliran(diterima=190, hilang=10)
    with caplog.at_level(logging.INFO, logger=frame_capture_worker.logger.name):
        line.jalan(10)                                   # read at second 10
    assert line.state.frame_hilang.ringkas(line.jam.sekarang) == (10, 200)
    hilang = [r for r in caplog.records if "kehilangan gambar" in r.getMessage()]
    assert [r.levelno for r in hilang] == [logging.WARNING]
    assert "10 dari 200" in hilang[0].getMessage()


def test_frame_hilang_pulih_sesudah_jendela_lewat(caplog):
    line = LinePalsu()
    line.kamera.statistik = StatistikAliran(diterima=0, hilang=0)
    line.jalan(10)
    line.kamera.statistik = StatistikAliran(diterima=190, hilang=10)
    with caplog.at_level(logging.INFO, logger=frame_capture_worker.logger.name):
        line.jalan(10)
        line.kamera.statistik = StatistikAliran(diterima=10_000, hilang=10)   # no new loss
        line.jalan(620)
    pesan = [m for m in _log(caplog) if "kehilangan gambar" in m]
    assert len(pesan) == 2 and "tidak kehilangan gambar lagi" in pesan[1]


def test_sumber_tanpa_statistik_tidak_mengisi_jendela():
    line = LinePalsu()
    line.jalan(30)
    assert line.state.frame_hilang.ringkas(line.jam.sekarang) is None


def test_putus_dihitung_sekali_per_kejadian():
    line = LinePalsu()
    line.jalan(2)
    line.kamera.mengirim = False
    line.jalan(12, deteksi=False)        # many failed grabs, one incident
    line.kamera.mengirim = True
    line.jalan(2)
    line.kamera.mengirim = False
    line.jalan(12, deteksi=False)
    assert line.state.putus_kamera.jumlah(line.jam.sekarang) == 2


def test_kamera_tanpa_sensor_tidak_ditanya_suhu_lagi():
    line = LinePalsu()
    line.kamera.suhu_didukung = False
    line.jalan(30)
    assert line.kamera.suhu_dibaca == 0
    assert line.state.suhu_kamera_didukung is False


def test_galat_statistik_tidak_menjatuhkan_capture(caplog):
    line = LinePalsu()
    line.kamera.statistik_melempar = True
    with caplog.at_level(logging.DEBUG, logger=frame_capture_worker.logger.name):
        line.jalan(25)
    assert line.state.frame_terakhir_at == 1_024.0
    galat = [r.levelno for r in caplog.records if "stream counters" in r.getMessage()]
    assert galat == [logging.WARNING, logging.DEBUG, logging.DEBUG]
