"""Bit PLC (blok M1100..) -> daftar alarm yang bisa dibaca manusia.

Logika murni, nol I/O, supaya bisa dites tanpa PLC dan tanpa cv2/torch.
Offset mengikuti daftar pak Ocit 2026-09-23: 0-10 motor 1-11 fault, 11 E-stop.
"""
from palmgrade.domain.plc_alarm import (
    ALARM_ESTOP,
    ALARM_MOTOR_FAULT,
    ESTOP_OFFSET,
    MOTOR_COUNT,
    alarms_from_inputs,
)


def _bits(*aktif: int, panjang: int = 16) -> list[bool]:
    b = [False] * panjang
    for i in aktif:
        b[i] = True
    return b


def test_tanpa_bit_aktif_tidak_ada_alarm():
    assert alarms_from_inputs(_bits()) == []


def test_inputs_kosong_berarti_tidak_ada_alarm_bukan_error():
    # PLC mati (PLC_ENABLED=false) -> plc.inputs() = []. Layar harus tenang.
    assert alarms_from_inputs([]) == []


def test_motor_dinomori_dari_satu_bukan_nol():
    # Offset 2 = MOTOR 3 di daftar Ocit (M1102). Salah satu, teknisi buka panel motor yang salah.
    assert alarms_from_inputs(_bits(2)) == [{"code": ALARM_MOTOR_FAULT, "n": 3}]


def test_motor_terakhir_adalah_sebelas():
    assert alarms_from_inputs(_bits(MOTOR_COUNT - 1)) == [{"code": ALARM_MOTOR_FAULT, "n": 11}]


def test_estop_di_offset_sebelas():
    assert ESTOP_OFFSET == 11
    assert alarms_from_inputs(_bits(11)) == [{"code": ALARM_ESTOP}]


def test_beberapa_alarm_urut_naik():
    assert alarms_from_inputs(_bits(11, 0, 4)) == [
        {"code": ALARM_MOTOR_FAULT, "n": 1},
        {"code": ALARM_MOTOR_FAULT, "n": 5},
        {"code": ALARM_ESTOP},
    ]


def test_bit_belum_dialokasikan_diabaikan():
    # 12-15 kosong di daftar Ocit. Kalau ladder memakainya untuk hal lain,
    # layar operator tidak boleh menyebutnya "motor 13".
    assert alarms_from_inputs(_bits(12, 15)) == []


def test_blok_lebih_pendek_dari_dua_belas_tetap_aman():
    assert alarms_from_inputs([True, False, False]) == [{"code": ALARM_MOTOR_FAULT, "n": 1}]
