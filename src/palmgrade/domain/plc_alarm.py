"""Bit yang dibaca dari PLC -> daftar alarm untuk layar operator.

Logika murni, nol I/O — pola yang sama dengan `plc_signal.py`. Offsetnya
mengikuti daftar pak Ocit 2026-09-23 (blok mulai `PLC_DI_BASE`, M1100):

    offset 0..10  MOTOR 1..11 FAULT   (M1100..M1110)
    offset 11     E-STOP OP PANEL     (M1111)
    offset 12..15 belum dialokasikan  (M1112..M1115)

Modul ini sengaja tidak tahu angka 1100: `PlcWorker` sudah menyimpan blok
sebagai daftar mulai offset 0, dan `PLC_DI_BASE` boleh berubah tanpa
menyentuh apa pun di sini.

Kode alarm bahasa-netral; teks manusia hidup di KAMUS konsol, dua bahasa.

⚠️ Polaritas: bit ON dianggap "fault / ditekan". Daftar Ocit tidak menyebut
polaritas — dicatat sebagai butir konfirmasi di docs/plc-mc-handoff.md,
bukan dikompensasi di sini.
"""
from __future__ import annotations

ALARM_MOTOR_FAULT = "motor_fault"
ALARM_ESTOP = "estop"

#: Motor 1..11 menempati offset 0..10.
MOTOR_COUNT = 11
#: E-stop tepat sesudah motor terakhir.
ESTOP_OFFSET = MOTOR_COUNT

#: Semua kode yang bisa muncul — dipakai test konsol untuk memastikan
#: tiap kode punya terjemahan di kedua bahasa.
ALARM_CODES = (ALARM_MOTOR_FAULT, ALARM_ESTOP)


def alarms_from_inputs(inputs: list[bool]) -> list[dict]:
    """Bit yang ON -> alarm, urut naik. Bit di luar 0..11 diabaikan.

    `[]` untuk PLC mati (`inputs` kosong) dan untuk blok tanpa bit aktif —
    keduanya berarti "layar tenang", bukan error.
    """
    alarms: list[dict] = []
    for offset in range(min(len(inputs), MOTOR_COUNT)):
        if inputs[offset]:
            alarms.append({"code": ALARM_MOTOR_FAULT, "n": offset + 1})
    if len(inputs) > ESTOP_OFFSET and inputs[ESTOP_OFFSET]:
        alarms.append({"code": ALARM_ESTOP})
    return alarms
