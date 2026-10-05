"""What the Hikrobot camera tells the health watch: stream counters, and whether it has a
temperature sensor at all.

Lampung 2026-10-05: `DeviceTemperature` has access mode NI on the MV-CS050-10GC, so the
camera is asked once per connect and then left alone, and the card can say "not supported"
instead of a dash that reads like a fault.
"""
from __future__ import annotations

import logging
import sys
import types
from ctypes import POINTER, Structure, c_int, c_int64, c_uint, c_void_p, cast

import pytest

from palmgrade.domain.kesehatan_kamera import StatistikAliran
from palmgrade.integrations.camera import hikrobot_camera
from palmgrade.integrations.camera.base import CameraSource
from palmgrade.integrations.camera.hikrobot_camera import HikrobotCamera

AM_NI, AM_NA, AM_RO = 0, 1, 3
MV_E_SUPPORT = 0x80000001
MV_E_GC_ACCESS = 0x80000106
MV_MATCH_TYPE_NET_DETECT = 0x00000001


class _Float:
    def __init__(self) -> None:
        self.fCurValue = 0.0


class _AllMatchInfo(Structure):
    _fields_ = [("nType", c_uint), ("pInfo", c_void_p), ("nInfoSize", c_uint)]


class _NetDetect(Structure):
    _fields_ = [
        ("nReceiveDataSize", c_int64), ("nLostPacketCount", c_int64), ("nLostFrameCount", c_uint),
        ("nNetRecvFrameCount", c_uint), ("nRequestResendPacketCount", c_int64), ("nResendPacketCount", c_int64),
    ]


@pytest.fixture
def sdk_palsu(monkeypatch):
    sdk = types.ModuleType("MvImport.MvCameraControl_class")
    sdk.MVCC_FLOATVALUE = _Float
    sdk.MV_XML_AccessMode = c_int
    sdk.MV_ALL_MATCH_INFO = _AllMatchInfo
    sdk.MV_MATCH_INFO_NET_DETECT = _NetDetect
    sdk.MV_MATCH_TYPE_NET_DETECT = MV_MATCH_TYPE_NET_DETECT
    monkeypatch.setitem(sys.modules, "MvImport", types.ModuleType("MvImport"))
    monkeypatch.setitem(sys.modules, "MvImport.MvCameraControl_class", sdk)


class _Sdk:
    def __init__(self, *, akses: int = AM_RO, akses_ret: int = 0, suhu: float = 47.0, suhu_ret: int = 0,
                 diterima: int = 0, hilang: int = 0, statistik_ret: int = 0) -> None:
        self.akses, self.akses_ret = akses, akses_ret
        self.suhu, self.suhu_ret = suhu, suhu_ret
        self.diterima, self.hilang, self.statistik_ret = diterima, hilang, statistik_ret
        self.panggilan: list[str] = []

    def MV_XML_GetNodeAccessMode(self, node, wadah):  # noqa: N802
        self.panggilan.append(f"akses:{node}")
        wadah.value = self.akses
        return self.akses_ret

    def MV_CC_GetFloatValue(self, node, wadah):  # noqa: N802
        self.panggilan.append(f"float:{node}")
        wadah.fCurValue = self.suhu
        return self.suhu_ret

    def MV_CC_GetAllMatchInfo(self, info):  # noqa: N802
        self.panggilan.append(f"match:{info.nType}")
        if self.statistik_ret == 0:
            net = cast(info.pInfo, POINTER(_NetDetect)).contents
            assert info.nInfoSize >= 8  # the caller sized the buffer
            net.nNetRecvFrameCount, net.nLostFrameCount = self.diterima, self.hilang
        return self.statistik_ret


def _kamera(sdk: _Sdk, *, connected: bool = True) -> HikrobotCamera:
    kamera = HikrobotCamera.__new__(HikrobotCamera)
    kamera.connected = connected
    kamera.cam = sdk
    return kamera


# ── temperature sensor present or not ────────────────────────────────────────


def test_tanpa_sensor_ditanya_sekali_lalu_tidak_lagi(sdk_palsu, caplog):
    sdk = _Sdk(akses=AM_NI, suhu_ret=MV_E_GC_ACCESS)
    kamera = _kamera(sdk)
    with caplog.at_level(logging.DEBUG, logger=hikrobot_camera.logger.name):
        for _ in range(5):
            assert kamera.get_temperature() is None
    assert sdk.panggilan == ["akses:DeviceTemperature"]
    assert kamera.suhu_didukung is False
    # Not a fault: one INFO, never the WARNING a refused reading gets.
    assert [r.levelno for r in caplog.records] == [logging.INFO]
    assert "DeviceTemperature" in caplog.records[0].getMessage()


def test_sensor_ada_dibaca_dan_ditandai_didukung(sdk_palsu):
    sdk = _Sdk(akses=AM_RO, suhu=47.34)
    kamera = _kamera(sdk)
    assert kamera.get_temperature() == 47.3
    assert kamera.get_temperature() == 47.3
    assert kamera.suhu_didukung is True
    assert sdk.panggilan.count("akses:DeviceTemperature") == 1   # asked once, not per reading


def test_sensor_belum_tersedia_tetap_dicoba(sdk_palsu):
    """NA = implemented but not available now: maybe later, so keep asking."""
    kamera = _kamera(_Sdk(akses=AM_NA, suhu_ret=MV_E_GC_ACCESS))
    assert kamera.get_temperature() is None
    assert kamera.suhu_didukung is None


def test_sdk_tanpa_jawaban_akses_tetap_membaca(sdk_palsu):
    sdk = _Sdk(akses_ret=MV_E_SUPPORT, suhu=40.0)
    assert _kamera(sdk).get_temperature() == 40.0


def test_sumber_lain_tidak_tahu_soal_sensor():
    class _Webcam(CameraSource):
        def connect(self, index=0, serial=None, feature_file=None): ...
        def grab_frame(self): ...
        def disconnect(self): ...

    webcam = _Webcam()
    assert webcam.suhu_didukung is None
    assert webcam.get_statistik_aliran() is None


# ── stream counters ──────────────────────────────────────────────────────────


def test_statistik_aliran_dari_net_detect(sdk_palsu):
    sdk = _Sdk(diterima=12_000, hilang=7)
    assert _kamera(sdk).get_statistik_aliran() == StatistikAliran(diterima=12_000, hilang=7)
    assert sdk.panggilan == [f"match:{MV_MATCH_TYPE_NET_DETECT}"]


def test_statistik_kamera_tidak_tersambung_tidak_ditanya(sdk_palsu):
    sdk = _Sdk()
    assert _kamera(sdk, connected=False).get_statistik_aliran() is None
    assert sdk.panggilan == []


def test_statistik_gagal_warning_sekali_dengan_kode(sdk_palsu, caplog):
    kamera = _kamera(_Sdk(statistik_ret=MV_E_SUPPORT))
    with caplog.at_level(logging.DEBUG, logger=hikrobot_camera.logger.name):
        for _ in range(3):
            assert kamera.get_statistik_aliran() is None
    assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.DEBUG, logging.DEBUG]
    assert "0x80000001 (MV_E_SUPPORT)" in caplog.records[0].getMessage()
