"""Display label for Sumber TBS, the FFB source (plan §3.5b).

In AutoERP the source is an Accounting Dimension, not a boolean, and the ERP
derives it itself: fruit with a supplier is External, fruit without one is the
mill's own. The distinction between kinds of external supplier — plasma, agent,
anyone else — lives on the Supplier Group, which is master data an admin can
add to at any time.

So the edge stores what it was given RAW and only renders it. Never store
`is_internal` here: flatten the source to two values at the edge and the
Plasma vs Pihak Ketiga reporting upstream can no longer be reconstructed.
"""
from __future__ import annotations

# The only value that is not bought. Everything else names a kind of supplier —
# an open set, so it is matched by "is not this one" rather than by a list that
# would silently render "—" the day someone adds a group in AutoERP.
_INTERNAL = {"inti", "internal"}


def label_sumber(sumber: str | None) -> str | None:
    """Raw master value -> display label. None = no source yet (renders "—")."""
    key = (sumber or "").strip().lower()
    if not key:
        return None
    return "Internal" if key in _INTERNAL else "External"
