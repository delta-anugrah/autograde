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


def test_parse_coil_list_degrades_to_empty_on_garbage():
    # Dulu ini raise. `PLC_COIL_ALIVE=9,10,` (koma nyantol) -> int('') -> ValueError
    # saat konstruksi Settings -> kontainer tidak pernah start. Ini knob subsistem
    # OPSIONAL yang default-nya mati, diedit operator jam 2 pagi saat commissioning:
    # typo di situ boleh mematikan bit alive, tidak boleh mematikan grading.
    assert parse_coil_list("9,abc") == ()
    assert parse_coil_list("9,10,") == ()


def test_malformed_plc_env_falls_back_to_default_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("PLC_POLL_MS", "dua ratus")
    monkeypatch.setenv("PLC_QUEUE_MAX", "")
    monkeypatch.setenv("PLC_COIL_ALIVE", "9,10,")

    s = Settings()          # tidak boleh raise

    assert s.plc_poll_ms == 200
    assert s.plc_queue_max == 1
    assert s.plc_coil_alive == ()


def test_non_plc_int_env_still_fails_fast(monkeypatch):
    # Parser toleran itu KHUSUS field PLC. Field lain tidak boleh ikut melunak.
    monkeypatch.setenv("UPLOAD_RETENTION_DAYS", "abc")
    with pytest.raises(ValueError):
        Settings()
