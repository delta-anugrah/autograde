"""Reading the camera settings nodes through the SDK (capture thread only, under `state.lock`).

Phase 0 on the Lampung camera (2026-10-05): ExposureTime 4000 (15 to 9959540), Gain 0, BlackLevel 240 as an
integer, AcquisitionFrameRate 20, BalanceWhiteAuto Continuous, ExposureAuto and GainAuto Off.
"""
from __future__ import annotations

import sys
import types

import pytest

from palmgrade.domain.setelan_kamera import NilaiSetelan
from palmgrade.integrations.camera.base import CameraSource
from palmgrade.integrations.camera.hikrobot_camera import HikrobotCamera
from palmgrade.integrations.camera.setelan_hikrobot import baca_setelan_hikrobot

MV_E_GC_ACCESS = 0x80000106


class _Float:
    def __init__(self) -> None:
        self.fCurValue = self.fMin = self.fMax = 0.0


class _Int:
    def __init__(self) -> None:
        self.nCurValue = self.nMin = self.nMax = self.nInc = 0


class _Enum:
    def __init__(self) -> None:
        self.nCurValue = 0
        self.nSupportedNum = 0
        self.nSupportValue = [0] * 64


class _Entry:
    def __init__(self) -> None:
        self.nValue = 0
        self.chSymbolic = b""


@pytest.fixture(autouse=True)
def sdk_palsu(monkeypatch):
    sdk = types.ModuleType("MvImport.MvCameraControl_class")
    sdk.MVCC_FLOATVALUE, sdk.MVCC_INTVALUE_EX, sdk.MVCC_ENUMVALUE, sdk.MVCC_ENUMENTRY = _Float, _Int, _Enum, _Entry
    monkeypatch.setitem(sys.modules, "MvImport", types.ModuleType("MvImport"))
    monkeypatch.setitem(sys.modules, "MvImport.MvCameraControl_class", sdk)


ENUM_SIMBOL = {0: b"Off", 1: b"Once", 2: b"Continuous"}


class _Sdk:
    """Answers like the Lampung camera; `tolak` = nodes this firmware refuses."""

    def __init__(self, tolak: tuple[str, ...] = ()) -> None:
        self.tolak = tolak
        self.float = {"ExposureTime": (4000.0, 15.0, 9959540.0), "Gain": (0.0, 0.0, 23.981199264526367),
                      "AcquisitionFrameRate": (20.0, 0.1, 100000.0)}
        self.int = {"BlackLevel": (240, 0, 4095, 1)}
        self.enum = {"BalanceWhiteAuto": (2, [0, 1, 2]), "ExposureAuto": (0, [0, 1, 2]), "GainAuto": (0, [0, 1, 2])}

    def MV_CC_GetFloatValue(self, node, v):  # noqa: N802
        if node in self.tolak:
            return MV_E_GC_ACCESS
        v.fCurValue, v.fMin, v.fMax = self.float[node]
        return 0

    def MV_CC_GetIntValueEx(self, node, v):  # noqa: N802
        if node in self.tolak:
            return MV_E_GC_ACCESS
        v.nCurValue, v.nMin, v.nMax, v.nInc = self.int[node]
        return 0

    def MV_CC_GetEnumValue(self, node, v):  # noqa: N802
        if node in self.tolak:
            return MV_E_GC_ACCESS
        cur, didukung = self.enum[node]
        v.nCurValue, v.nSupportedNum = cur, len(didukung)
        v.nSupportValue[: len(didukung)] = didukung
        return 0

    def MV_CC_GetEnumEntrySymbolic(self, node, entri):  # noqa: N802
        entri.chSymbolic = ENUM_SIMBOL[entri.nValue]
        return 0


def _per_kunci(nilai: list[NilaiSetelan]) -> dict[str, NilaiSetelan]:
    return {n.kunci: n for n in nilai}


def test_semua_node_terbaca_seperti_kamera_lampung():
    n = _per_kunci(baca_setelan_hikrobot(_Sdk()))
    assert n["exposure"] == NilaiSetelan("exposure", 4000.0, 15.0, 9959540.0)
    assert n["black_level"] == NilaiSetelan("black_level", 240, 0, 4095, 1)
    assert n["white_balance"] == NilaiSetelan("white_balance", "Continuous", pilihan=("Off", "Once", "Continuous"))
    assert n["exposure_auto"].nilai == "Off"
    assert n["frame_rate"].nilai == 20.0
    assert len(n) == 7


def test_node_yang_ditolak_jadi_satu_baris_dengan_kode_lainnya_tetap():
    n = _per_kunci(baca_setelan_hikrobot(_Sdk(tolak=("BalanceWhiteAuto",))))
    assert n["white_balance"].didukung is False
    assert n["white_balance"].kode_galat == "0x80000106"   # `format_mvs_ret` has no name for this code
    assert n["exposure"].didukung is True


def test_hikrobot_tidak_tersambung_menolak_bukan_membaca():
    kamera = HikrobotCamera.__new__(HikrobotCamera)
    kamera.connected = False
    kamera.cam = _Sdk()
    with pytest.raises(RuntimeError, match="not connected"):
        kamera.baca_setelan()


def test_hikrobot_tersambung_membaca():
    kamera = HikrobotCamera.__new__(HikrobotCamera)
    kamera.connected = True
    kamera.cam = _Sdk()
    assert HikrobotCamera.punya_setelan is True
    assert len(kamera.baca_setelan()) == 7


def test_sumber_lain_tidak_punya_setelan():
    class _Webcam(CameraSource):
        def connect(self, index=0, serial=None, feature_file=None): ...
        def grab_frame(self): ...
        def disconnect(self): ...

    assert _Webcam().punya_setelan is False
    with pytest.raises(NotImplementedError):
        _Webcam().baca_setelan()
