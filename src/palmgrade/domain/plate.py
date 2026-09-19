"""Normalised plate number, the cross-system key.

Scale, ERP and operator write the same plate differently ("B 1234 XY", "b1234xy",
"B-1234-XY"). Always compare the normalised form; keep the raw text for display.
"""
from __future__ import annotations

import re
import uuid

from .operator_error import PLAT_KOSONG, InvalidInput

_BUKAN_ALNUM = re.compile(r"[^A-Za-z0-9]")


def normalisasi_plat(plat: str) -> str:
    """`B 1234 xy` → `B1234XY`. ValueError if nothing is left."""
    hasil = _BUKAN_ALNUM.sub("", plat or "").upper()
    if not hasil:
        raise InvalidInput(PLAT_KOSONG, "nomor polisi tidak boleh kosong")
    return hasil


def truck_id_for(plat: str) -> str:
    """Deterministic local truck id (uuid5, like `domain/vision_event.py`).

    A plate retyped on another shift must be the same truck, not a twin row
    that splits its tonnage.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"truk:{normalisasi_plat(plat)}"))
