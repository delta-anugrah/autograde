from palmgrade.integrations.camera.mvs_error import format_mvs_ret


def test_known_code_shows_hex_and_name():
    assert format_mvs_ret(0x80000203) == "0x80000203 (MV_E_ACCESS_DENIED)"


def test_ok_code():
    assert format_mvs_ret(0) == "0x00000000 (MV_OK)"


def test_negative_signed_int_normalized_to_unsigned():
    # SDK/ctypes bisa balikin int signed; 0x80000203 as signed = -2147483133
    assert format_mvs_ret(-2147483133) == "0x80000203 (MV_E_ACCESS_DENIED)"


def test_unknown_code_falls_back_to_hex_only():
    assert format_mvs_ret(0x80000099) == "0x80000099"


def test_timeout_code():
    assert format_mvs_ret(0x80000204) == "0x80000204 (MV_E_TIMEOUT)"
