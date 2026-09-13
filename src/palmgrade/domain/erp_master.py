"""Translate an AutoERP master-data document into a console row.

Pure: no HTTP, no SQLite. AutoERP owns suppliers and trucks and the console only
copies them down, so everything here is a translation and never a decision — the
supplier group in particular rides down raw (§3.5b).
"""
from __future__ import annotations

import uuid
from typing import Any

from .plate import truck_id_for


def supplier_id_for(erp_name: str) -> str:
    """Deterministic local id for an ERP supplier, the way plates get one.

    ERP names a Supplier by its display name; the console keys on an opaque id,
    so the same ERP name must always resolve to the same local row.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"supplier:{erp_name}"))


def _status(doc: dict[str, Any]) -> str:
    """Disabled upstream stays visible, marked — never dropped."""
    return "inactive" if doc.get("disabled") else "active"


def supplier_row(doc: dict[str, Any]) -> dict[str, Any]:
    erp_name = doc["name"]
    return {
        "id": supplier_id_for(erp_name),
        "erp_name": erp_name,
        "name": doc.get("supplier_name") or erp_name,
        "sumber": doc.get("supplier_group"),
        "status": _status(doc),
    }


def truck_row(doc: dict[str, Any]) -> dict[str, Any]:
    """The id comes from the plate, so an ERP truck adopts the operator's row.

    Both sides normalise a plate identically (upper-case, non-alphanumerics
    stripped), which is what lets one truck stay one row across the two systems.
    """
    erp_name = doc["name"]
    plate = doc.get("plate_number") or erp_name
    supplier = doc.get("supplier")
    return {
        "id": truck_id_for(plate),
        "erp_name": erp_name,
        "plate_number": plate,
        "supplier_id": supplier_id_for(supplier) if supplier else None,
        "status": _status(doc),
    }
