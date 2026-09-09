"""Label tampilan Sumber TBS (§3.5b rencana PalmOS).

Sumber ada TIGA (Inti / Plasma / Pihak Ketiga) dan itu Accounting Dimension di
PalmOS — bukan boolean. Edge tidak pernah MENENTUKAN sumber: nilainya ikut
turun bersama master data supplier, konsol cuma menampilkannya. Jangan pernah
menyimpan `is_internal` di sini; begitu sumber dipadatkan jadi 2 nilai di edge,
laporan Plasma vs Pihak Ketiga di cloud tidak bisa direkonstruksi lagi.
"""
from __future__ import annotations

_INTERNAL = {"inti"}
_EXTERNAL = {"plasma", "pihak ketiga"}


def label_sumber(sumber: str | None) -> str | None:
    """3 nilai master → label tampilan. None = belum ada sumber (render "—")."""
    key = (sumber or "").strip().lower()
    if key in _INTERNAL:
        return "Internal"
    if key in _EXTERNAL:
        return "External"
    return None
