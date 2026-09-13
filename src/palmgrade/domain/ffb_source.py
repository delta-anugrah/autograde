"""FFB source label (Sumber TBS) for the console screens (§3.5b).

AutoERP decides the source, not the edge: `sumber_for_supplier` in
`erpnext/palm_mill` files fruit with a supplier as External and fruit without
one as the mill's own. The console mirrors that rule and nothing more.

Plasma vs agent lives on the Supplier Group upstream. Never flatten it into an
`is_internal` flag here, or that reporting cannot be rebuilt.
"""
from __future__ import annotations


def ffb_source_label(*, has_supplier: bool, in_erp: bool) -> str | None:
    """Label for one truck. None renders as "—".

    An ownerless truck is Internal only once AutoERP holds it; before that the
    console has no source to show.
    """
    if has_supplier:
        return "External"
    return "Internal" if in_erp else None
