"""Display label for Sumber TBS, the FFB source (plan §3.5b).

There are THREE sources (Inti / Plasma / Pihak Ketiga) and in PalmOS they are an
Accounting Dimension, not a boolean. The edge never DECIDES the source: the
value rides down with supplier master data and the console only renders it.
Never store `is_internal` here; once three values are flattened to two at the
edge, the cloud's Plasma vs Pihak Ketiga reporting cannot be reconstructed.
"""
from __future__ import annotations

_INTERNAL = {"inti"}
_EXTERNAL = {"plasma", "pihak ketiga"}


def label_sumber(sumber: str | None) -> str | None:
    """3 master values -> display label. None = no source yet (renders "—")."""
    key = (sumber or "").strip().lower()
    if key in _INTERNAL:
        return "Internal"
    if key in _EXTERNAL:
        return "External"
    return None
