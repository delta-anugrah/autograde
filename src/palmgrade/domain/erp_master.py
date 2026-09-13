"""Translate AutoERP master-data documents into console rows.

Pure: no HTTP, no SQLite. AutoERP owns suppliers and trucks (contract §2); the
console copies them down and decides nothing.
"""
from __future__ import annotations

import uuid
from typing import Any

from .plate import truck_id_for


def supplier_id_for(erp_name: str) -> str:
    """Stable local id for an AutoERP supplier, so one name is always one row."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"supplier:{erp_name}"))


def supplier_row(doc: dict[str, Any]) -> dict[str, Any]:
    erp_name = doc["name"]
    return {
        "id": supplier_id_for(erp_name),
        "erp_name": erp_name,
        "name": doc.get("supplier_name") or erp_name,
        # Raw group: AutoERP keeps Plasma vs agent here.
        "sumber": doc.get("supplier_group"),
        # Marked, never dropped: history still points at it.
        "status": "inactive" if doc.get("disabled") else "active",
    }


def truck_row(doc: dict[str, Any]) -> dict[str, Any]:
    """The id comes from the plate, so an ERP truck adopts the operator's row.

    Both systems normalise plates the same way (`normalize_plate` in AutoERP),
    which keeps one truck on one row across the two.
    """
    erp_name = doc["name"]
    plate = doc.get("plate_number") or erp_name
    supplier = doc.get("supplier")
    return {
        "id": truck_id_for(plate),
        "erp_name": erp_name,
        "plate_number": plate,
        "supplier_id": supplier_id_for(supplier) if supplier else None,
        # AutoERP's Truck has no `disabled` field.
        "status": "active",
    }
