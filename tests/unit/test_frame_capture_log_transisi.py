"""Kamera yang berhenti mengirim gambar = satu baris, bukan ±10 per detik (batch 3.3).

Dulu tiap grab gagal satu WARNING dari adaptor Hikrobot, tiap sambung ulang satu
WARNING, tiap sambung ulang yang gagal satu ERROR. Sekarang satu WARNING saat kamera
berhenti (dengan alasan terakhir), satu ERROR untuk sambung ulang pertama yang
gagal, dan satu WARNING saat gambar datang lagi.
"""
from __future__ import annotations

import logging

import numpy as np
import pytest

from palmgrade.integrations.camera import hikrobot_camera
from palmgrade.integrations.camera.base import CameraSource
from palmgrade.integrations.camera.hikrobot_camera import HikrobotCamera
from palmgrade.workers import frame_capture_worker as modul
from palmgrade.workers.frame_capture_worker import FrameCaptureWorker
from palmgrade.workers.runtime_state import RuntimeState


class _Kamera(CameraSource):
    """`mengirim=False` = grab gagal; `bisa_sambung=False` = sambung ulang melempar."""

    def __init__(self, *, sambung_ulang: bool = True) -> None:
        super().__init__()
        self.connected = True
        self.mengirim = True
        self.bisa_sambung = True
        self._sambung_ulang = sambung_ulang

    def connect(self, index=0, serial=None, feature_file=None) -> None:
        if not self.bisa_sambung:
            raise RuntimeError("MV_E_NODATA")
        self.connected = True

    def grab_frame(self):
        if not self.mengirim:
            self.galat_terakhir = "grab gagal, kode 0x80000007"
            return None
        return np.zeros((4, 4, 3), dtype=np.uint8)

    def disconnect(self) -> None:
        self.connected = False

    @property
    def supports_reconnect(self) -> bool:
        return self._sambung_ulang


@pytest.fixture(autouse=True)
def _tanpa_tidur(monkeypatch):
    monkeypatch.setattr(modul.time, "sleep", lambda _s: None)


def _worker(kamera: _Kamera) -> FrameCaptureWorker:
    return FrameCaptureWorker(camera=kamera, state=RuntimeState(), target_fps=0)


def _log(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == modul.logger.name and r.levelno >= logging.WARNING]


def test_kamera_putus_lama_satu_warning_satu_error_lalu_satu_saat_kembali(caplog):
    kamera = _Kamera()
    worker = _worker(kamera)
    with caplog.at_level(logging.DEBUG, logger=modul.logger.name):
        worker.run_once()
        kamera.mengirim = False
        kamera.bisa_sambung = False
        for _ in range(200):
            worker.run_once()
        kamera.mengirim = True
        kamera.bisa_sambung = True
        for _ in range(3):
            worker.run_once()

    catatan = _log(caplog)
    assert [r.levelname for r in catatan] == ["WARNING", "ERROR", "WARNING"]
    assert "5 kali gagal berturut" in catatan[0].getMessage()
    assert "0x80000007" in catatan[0].getMessage()
    assert "MV_E_NODATA" in catatan[1].getMessage()
    assert catatan[2].getMessage().startswith("Kamera mengirim gambar lagi sesudah")


def test_frame_terpotong_sesekali_tidak_menulis_apa_pun(caplog):
    kamera = _Kamera()
    worker = _worker(kamera)
    with caplog.at_level(logging.WARNING, logger=modul.logger.name):
        for _ in range(50):
            kamera.mengirim = False
            worker.run_once()
            worker.run_once()
            kamera.mengirim = True
            worker.run_once()
    assert _log(caplog) == []


def test_kejadian_kedua_ditulis_lagi(caplog):
    kamera = _Kamera(sambung_ulang=False)
    worker = _worker(kamera)
    with caplog.at_level(logging.WARNING, logger=modul.logger.name):
        for _ in range(2):
            kamera.mengirim = False
            for _ in range(10):
                worker.run_once()
            kamera.mengirim = True
            worker.run_once()
    assert len(_log(caplog)) == 4


def test_sumber_tanpa_sambung_ulang_tidak_menyebut_menyambung_ulang(caplog):
    kamera = _Kamera(sambung_ulang=False)
    worker = _worker(kamera)
    kamera.mengirim = False
    with caplog.at_level(logging.WARNING, logger=modul.logger.name):
        for _ in range(10):
            worker.run_once()
    [catatan] = _log(caplog)
    assert "menyambung ulang" not in catatan.getMessage()


class _InfoFrame:
    def __init__(self) -> None:
        self.nFrameLen = 0
        self.nWidth = 4
        self.nHeight = 4
        self.enPixelType = 999


class _CamSdk:
    def __init__(self, ret: int) -> None:
        self.ret = ret

    def MV_CC_GetOneFrameTimeout(self, buf, size, info, timeout):  # noqa: N802 (nama milik SDK MVS)
        return self.ret


def _hikrobot(monkeypatch, ret: int) -> HikrobotCamera:
    """Tanpa SDK: konstruktor asli menolak jalan, jadi atributnya dipasang tangan."""
    monkeypatch.setattr(hikrobot_camera, "MV_FRAME_OUT_INFO_EX", _InfoFrame, raising=False)
    for nama, nilai in (("PixelType_Gvsp_Mono8", 1), ("PixelType_Gvsp_BayerRG8", 2), ("PixelType_Gvsp_RGB8_Packed", 3)):
        monkeypatch.setattr(hikrobot_camera, nama, nilai, raising=False)
    kamera = HikrobotCamera.__new__(HikrobotCamera)
    kamera.connected = True
    kamera.cam = _CamSdk(ret)
    kamera._data_buf = bytearray(64)
    kamera._buffer_size = 64
    return kamera


def test_hikrobot_grab_gagal_cuma_debug_dan_alasannya_disimpan(monkeypatch, caplog):
    kamera = _hikrobot(monkeypatch, 0x80000007)
    with caplog.at_level(logging.DEBUG, logger=hikrobot_camera.logger.name):
        for _ in range(20):
            assert kamera.grab_frame() is None
    assert all(r.levelno == logging.DEBUG for r in caplog.records)
    assert "0x80000007" in kamera.galat_terakhir


def test_hikrobot_format_piksel_asing_cuma_debug(monkeypatch, caplog):
    kamera = _hikrobot(monkeypatch, 0)
    with caplog.at_level(logging.DEBUG, logger=hikrobot_camera.logger.name):
        assert kamera.grab_frame() is None
    assert all(r.levelno == logging.DEBUG for r in caplog.records)
    assert kamera.galat_terakhir == "format piksel 999 tidak didukung"
