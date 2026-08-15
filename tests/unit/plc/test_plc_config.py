import os

import pytest

from palmgrade.core.config import Settings, parse_coil_list


def test_coil_offsets_derive_from_base():
    os.environ["PLC_COIL_BASE"] = "3"
    try:
        s = Settings()
        assert (s.plc_coil_ok, s.plc_coil_ng, s.plc_coil_error) == (3, 4, 5)
    finally:
        del os.environ["PLC_COIL_BASE"]


def test_plc_disabled_by_default():
    assert Settings().plc_enabled is False


def test_plc_queue_max_default_is_one():
    # Antrean pulse > 1 = staleness terakumulasi (queue_max * (pulse+gap)).
    # Sinyal yang telat menempel ke buah yang salah di belt — lebih buruk
    # daripada tidak ada sinyal. Default harus membeli staleness sesedikit mungkin.
    assert Settings().plc_queue_max == 1


def test_parse_coil_list_handles_blank_and_spaces():
    assert parse_coil_list("") == ()
    assert parse_coil_list(None) == ()
    assert parse_coil_list(" 9 , 10 ") == (9, 10)
    assert parse_coil_list("12") == (12,)


def test_parse_coil_list_rejects_garbage():
    with pytest.raises(ValueError):
        parse_coil_list("9,abc")
