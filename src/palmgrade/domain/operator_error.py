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
BUKAN_ANGKA = "bukan_angka"
NEGATIF = "negatif"
DI_BAWAH_MINIMUM = "di_bawah_minimum"
TARA_LEBIH_BESAR = "tara_lebih_besar"
LINE_TIDAK_DIKENAL = "line_tidak_dikenal"
LINE_TIDAK_MENJAWAB = "line_tidak_menjawab"
LINE_MENOLAK = "line_menolak"

CODES = (
    PLAT_KOSONG,
    BUKAN_ANGKA,
    NEGATIF,
    DI_BAWAH_MINIMUM,
    TARA_LEBIH_BESAR,
    LINE_TIDAK_DIKENAL,
    LINE_TIDAK_MENJAWAB,
    LINE_MENOLAK,
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
