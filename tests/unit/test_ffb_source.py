"""FFB source label (Sumber TBS) mirrors AutoERP's `sumber_for_supplier`.

AutoERP derives the source from the supplier alone: fruit with a supplier is
External, fruit without one is the mill's own. The console only mirrors that,
and shows nothing where AutoERP has not decided yet.
"""
from __future__ import annotations

from palmgrade.domain.ffb_source import ffb_source_label


def test_a_truck_with_a_supplier_is_external():
    assert ffb_source_label(has_supplier=True, in_erp=True) == "External"
    # The owner is already known, so this holds before AutoERP has the truck.
    assert ffb_source_label(has_supplier=True, in_erp=False) == "External"


def test_an_erp_truck_without_a_supplier_is_the_mills_own():
    assert ffb_source_label(has_supplier=False, in_erp=True) == "Internal"


def test_no_label_for_an_ownerless_truck_autoerp_has_not_seen():
    """Only AutoERP decides an ownerless truck; the console must not guess."""
    assert ffb_source_label(has_supplier=False, in_erp=False) is None
