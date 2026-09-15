"""The two console account roles, plus filtering for roles pulled from AutoERP.

Pure rules, no I/O: `console_repository` stores it, `routes/console.py` enforces it.
Only two roles on purpose — none of the developer screens split sensibly between
a third role, which would just be a second name for one of these.
"""

from __future__ import annotations

PERAN_OPERATOR = "operator"
PERAN_SUPPORT = "support"

_DIKENAL = frozenset({PERAN_OPERATOR, PERAN_SUPPORT})


def peran_sah(nilai: object) -> str:
    """A known role, or `operator`. Never raises: a bad row must still be able
    to sign in as a plain operator, not lock the mill's screen."""
    if not isinstance(nilai, str):
        return PERAN_OPERATOR
    bersih = nilai.strip().lower()
    return bersih if bersih in _DIKENAL else PERAN_OPERATOR


def parse_daftar_izin(mentah: str) -> frozenset[str]:
    """`PERAN_ERP_DIIZINKAN` as the set of roles ERP is allowed to grant."""
    if not mentah:
        return frozenset()
    return frozenset(
        bagian.strip().lower() for bagian in mentah.split(",") if bagian.strip()
    )


def saring_peran_erp(nilai: object, diizinkan: frozenset[str]) -> str:
    """Role from AutoERP, but only if this PC's allow-list grants it.

    The one brake the factory side can pull on its own: clear the setting and
    restart, and no ERP account can open a developer screen.
    """
    peran = peran_sah(nilai)
    return peran if peran in diizinkan else PERAN_OPERATOR
