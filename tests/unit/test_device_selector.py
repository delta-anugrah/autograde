"""Unit test pemilihan kamera by-serial (murni, tanpa SDK/hardware).

Pakai dummy struct yang meniru bentuk `MV_CC_DEVICE_INFO`:
`nTLayerType` + `SpecialInfo.stGigEInfo.chSerialNumber` (list int, ASCII+null-pad).
"""

import pytest

from palmgrade.integrations.camera.device_selector import (
    MV_GIGE_DEVICE,
    MV_USB_DEVICE,
    decode_serial,
    extract_serial,
    find_index_by_serial,
)


def _ubytes(text: str, size: int = 64) -> list[int]:
    """Serial ASCII → array byte null-terminated (meniru chSerialNumber)."""
    data = list(text.encode("ascii"))
    return data + [0] * (size - len(data))


class _SpecialInfo:
    def __init__(self, gige_serial=None, usb_serial=None):
        self.stGigEInfo = type("G", (), {"chSerialNumber": _ubytes(gige_serial or "")})()
        self.stUsb3VInfo = type("U", (), {"chSerialNumber": _ubytes(usb_serial or "")})()


class _DeviceInfo:
    def __init__(self, serial: str, tlayer: int = MV_GIGE_DEVICE):
        self.nTLayerType = tlayer
        if tlayer == MV_USB_DEVICE:
            self.SpecialInfo = _SpecialInfo(usb_serial=serial)
        else:
            self.SpecialInfo = _SpecialInfo(gige_serial=serial)


def test_decode_serial_stops_at_null():
    assert decode_serial(_ubytes("DA9069810")) == "DA9069810"


def test_decode_serial_strips_whitespace():
    assert decode_serial(list(b" DA123 \x00")) == "DA123"


def test_extract_serial_gige():
    dev = _DeviceInfo("DA9069810", MV_GIGE_DEVICE)
    assert extract_serial(dev) == "DA9069810"


def test_extract_serial_usb():
    dev = _DeviceInfo("USB777", MV_USB_DEVICE)
    assert extract_serial(dev) == "USB777"


def test_find_index_returns_correct_position():
    devs = [
        _DeviceInfo("DA9070001"),
        _DeviceInfo("DA9069810"),  # <- target di posisi 1
        _DeviceInfo("DA7538184"),
    ]
    assert find_index_by_serial(devs, "DA9069810") == 1


def test_find_index_is_order_independent():
    """Inti fix: serial sama harus ketemu berapa pun urutan enum-nya."""
    order_a = [_DeviceInfo("A1"), _DeviceInfo("B2"), _DeviceInfo("C3")]
    order_b = [_DeviceInfo("C3"), _DeviceInfo("A1"), _DeviceInfo("B2")]
    assert find_index_by_serial(order_a, "B2") == 1
    assert find_index_by_serial(order_b, "B2") == 2


def test_find_index_case_insensitive():
    devs = [_DeviceInfo("DA9069810")]
    assert find_index_by_serial(devs, "da9069810") == 0


def test_find_index_raises_when_serial_absent():
    devs = [_DeviceInfo("DA9070001"), _DeviceInfo("DA7538184")]
    with pytest.raises(ValueError, match="DA9069810"):
        find_index_by_serial(devs, "DA9069810")
