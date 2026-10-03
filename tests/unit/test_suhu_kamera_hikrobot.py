"""Suhu badan kamera Hikrobot (`DeviceTemperature`).

Jalur SDK-nya sama dengan `get_fps()`, dan kamera Lampung sudah terbukti tidak
melaporkan lajunya lewat jalur itu tanpa kode galat di log. Karena itu kegagalan
di sini WAJIB menyebut kode SDK-nya, sekali, lalu diam.
"""
from __future__ import annotations

import logging
import sys
import types

import pytest

from palmgrade.integrations.camera import hikrobot_camera
from palmgrade.integrations.camera.base import CameraSource
from palmgrade.integrations.camera.hikrobot_camera import HikrobotCamera

MV_E_SUPPORT = 0x80000001  # node tidak didukung firmware


class _Float:
    def __init__(self) -> None:
        self.fCurValue = 0.0


@pytest.fixture
def sdk_palsu(monkeypatch):
    sdk = types.ModuleType("MvImport.MvCameraControl_class")
    sdk.MVCC_FLOATVALUE = _Float
    monkeypatch.setitem(sys.modules, "MvImport", types.ModuleType("MvImport"))
    monkeypatch.setitem(sys.modules, "MvImport.MvCameraControl_class", sdk)


class _Sdk:
    def __init__(self, nilai: float = 0.0, ret: int = 0) -> None:
        self.nilai, self.ret, self.node = nilai, ret, []

    def MV_CC_GetFloatValue(self, node, wadah):  # noqa: N802
        self.node.append(node)
        wadah.fCurValue = self.nilai
        return self.ret


def _kamera(sdk: _Sdk, *, connected: bool = True) -> HikrobotCamera:
    kamera = HikrobotCamera.__new__(HikrobotCamera)
    kamera.connected = connected
    kamera.cam = sdk
    return kamera


def test_sumber_tanpa_sensor_menjawab_none():
    class _Webcam(CameraSource):
        def connect(self, index=0, serial=None, feature_file=None): ...
        def grab_frame(self): ...
        def disconnect(self): ...

    assert _Webcam().get_temperature() is None


def test_suhu_dibaca_dari_device_temperature(sdk_palsu):
    sdk = _Sdk(nilai=47.34)
    assert _kamera(sdk).get_temperature() == 47.3
    assert sdk.node == ["DeviceTemperature"]


def test_kamera_tidak_tersambung_tidak_ditanya(sdk_palsu):
    sdk = _Sdk(nilai=47.0)
    assert _kamera(sdk, connected=False).get_temperature() is None
    assert sdk.node == []


@pytest.mark.parametrize("nilai", [-273.0, 0.0, 400.0])
def test_angka_mustahil_dianggap_tidak_tahu(sdk_palsu, nilai):
    """Struct yang tidak cocok dengan versi SDK memberi 0 atau sampah, bukan suhu."""
    assert _kamera(_Sdk(nilai=nilai)).get_temperature() is None


def test_suhu_gagal_warning_sekali_dengan_kode_sdk(sdk_palsu, caplog):
    kamera = _kamera(_Sdk(ret=MV_E_SUPPORT))
    with caplog.at_level(logging.DEBUG, logger=hikrobot_camera.logger.name):
        for _ in range(3):
            assert kamera.get_temperature() is None
    assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.DEBUG, logging.DEBUG]
    pesan = caplog.records[0].getMessage()
    assert "DeviceTemperature" in pesan
    assert "0x80000001 (MV_E_SUPPORT)" in pesan


def test_warning_laju_menyebut_kode_sdk(sdk_palsu, caplog):
    """Supaya log Lampung berikutnya menjawab KENAPA lajunya tidak terbaca."""
    kamera = _kamera(_Sdk(ret=MV_E_SUPPORT))
    with caplog.at_level(logging.DEBUG, logger=hikrobot_camera.logger.name):
        assert kamera.get_fps() == 0.0
    pesan = caplog.records[0].getMessage()
    assert "ResultingFrameRate" in pesan and "0x80000001 (MV_E_SUPPORT)" in pesan
