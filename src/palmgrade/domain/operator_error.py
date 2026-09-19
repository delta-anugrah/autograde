"""Failures the operator reads: a stable code the console screen translates.

The screen is bilingual and a server sentence is not, so the sentence is built
on the screen from `code` + `params`. The server text stays as the exception
message — for logs, and for machine callers (the scale program) that read it.
"""
from __future__ import annotations

# Codes are part of the console ↔ console.html contract: renaming one leaves the
# screen showing the raw server text again. `test_console_html.py` checks both
# languages translate every code listed in CODES.
PLAT_KOSONG = "plat_kosong"
# Its own code, NOT shared with PLAT_KOSONG: the screen translates per code, and a
# QR holding a URL answered with "cannot be empty" would be the wrong message in
# front of the gate operator. Found in the browser, not in a test.
BUKAN_PLAT = "bukan_plat"
BUKAN_ANGKA = "bukan_angka"
NEGATIF = "negatif"
DI_BAWAH_MINIMUM = "di_bawah_minimum"
TARA_LEBIH_BESAR = "tara_lebih_besar"
LINE_TIDAK_DIKENAL = "line_tidak_dikenal"
LINE_TIDAK_MENJAWAB = "line_tidak_menjawab"
LINE_MENOLAK = "line_menolak"
# Login (Fase 4). `SANDI_SALAH` deliberately says nothing about which of the two was
# wrong, and is the same answer for an operator switched off.
SANDI_PENDEK = "sandi_pendek"
SANDI_SALAH = "sandi_salah"
TERKUNCI = "terkunci"
BELUM_MASUK = "belum_masuk"
# Signed in, but not a `support` account.
BUKAN_SUPPORT = "bukan_support"
# PLC test screen (support only) — the only console lane that moves hardware.
KONFIRMASI_KURANG = "konfirmasi_kurang"
PLC_SIBUK = "plc_sibuk"
COIL_TIDAK_DIKENAL = "coil_tidak_dikenal"

CODES = (
    PLAT_KOSONG,
    BUKAN_PLAT,
    BUKAN_ANGKA,
    NEGATIF,
    DI_BAWAH_MINIMUM,
    TARA_LEBIH_BESAR,
    LINE_TIDAK_DIKENAL,
    LINE_TIDAK_MENJAWAB,
    LINE_MENOLAK,
    SANDI_PENDEK,
    SANDI_SALAH,
    TERKUNCI,
    BELUM_MASUK,
    BUKAN_SUPPORT,
    KONFIRMASI_KURANG,
    PLC_SIBUK,
    COIL_TIDAK_DIKENAL,
)


class OperatorError(Exception):
    """A failure with a code the operator screen can put into words."""

    def __init__(self, code: str, message: str, **params: str | float) -> None:
        super().__init__(message)
        self.code = code
        self.params = params

    def as_detail(self) -> dict:
        """HTTP error body for the operator routes."""
        return {"code": self.code, "params": self.params, "message": str(self)}


class InvalidInput(OperatorError, ValueError):
    """Bad input — still a ValueError, so existing 400/404 handling holds."""
