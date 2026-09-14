"""What the console sends to AutoERP (contract §4).

Pure: the payload and the queue key, nothing else. The key is the natural key
AutoERP matches on, so the same thing queued twice is one message holding the
newest state — never two racing each other.

A section we have nothing for is left out rather than sent empty: every send
**replaces** the sections it carries, so an empty one would erase what AutoERP
already has.
"""
from __future__ import annotations

from typing import Any

from .plate import normalisasi_plat, truck_id_for

TRUCK = "truck"
VISIT = "visit"


def truck_message(plate_number: str) -> tuple[str, dict[str, Any]]:
    """Interface B: a plate first seen at the mill becomes a Truck in AutoERP.

    Supplier and vehicle class are deliberately left out. AutoERP owns them: the
    backoffice completes the truck there and the next pull brings it back down.
    """
    return normalisasi_plat(plate_number), {
        "plate_number": plate_number,
        "autograde_id": truck_id_for(plate_number),
    }


def visit_message(
    visit: dict[str, Any],
    grading: dict[str, Any] | None,
    *,
    site: str,
    emitted_at: str,
) -> tuple[str, dict[str, Any]]:
    """Interface C: one truck visit — the weighbridge row, and the AI result once
    the line assignment that belongs to it has closed.

    `weighing.time_in` is what dates the ticket in AutoERP, so a visit without it
    is not sendable at all (`ErpQueue` refuses it before we get here).
    """
    payload: dict[str, Any] = {
        "visit_id": visit["id"],
        "stage": _stage(visit, grading),
        "truck": _truck(visit),
        "weighing": _weighing(visit),
        "emitted_at": emitted_at,
    }
    if site:
        payload["site"] = site
    if visit.get("supplier_erp_name"):
        payload["supplier_erp_name"] = visit["supplier_erp_name"]
    if visit.get("ref"):
        payload["scale_ticket_no"] = visit["ref"]
    if grading:
        payload["grading"] = _grading(grading)
    return visit["id"], payload


def _truck(visit: dict[str, Any]) -> dict[str, Any]:
    """AutoERP resolves `erp_name` before the plate, so send it whenever we have it.

    Without it, a plate whose text the backoffice corrected upstream normalises to a
    different key here, and AutoERP creates a SECOND Truck: the visit books onto a twin
    that splits the plate's tonnage. Left out entirely while unknown — that is the
    owner-less truck interface B creates.
    """
    truck: dict[str, Any] = {
        "plate_number": visit["plate_number"],
        "autograde_id": visit["truck_id"] or truck_id_for(visit["plate_number"]),
    }
    if visit.get("truck_erp_name"):
        truck["erp_name"] = visit["truck_erp_name"]
    return truck


def _stage(visit: dict[str, Any], grading: dict[str, Any] | None) -> str:
    """Informational for AutoERP, but it must not claim the truck is still here."""
    if visit.get("tara_kg") is not None:
        return "departed"
    return "grading" if grading else "gate"


def _weighing(visit: dict[str, Any]) -> dict[str, Any]:
    weighing: dict[str, Any] = {"time_in": visit["waktu_masuk"]}
    for ours, theirs in (("bruto_kg", "gross_kg"), ("tara_kg", "tare_kg")):
        if visit.get(ours) is not None:
            weighing[theirs] = float(visit[ours])
    if visit.get("waktu_keluar"):
        weighing["time_out"] = visit["waktu_keluar"]
    return weighing


def _grading(grading: dict[str, Any]) -> dict[str, Any]:
    """Criteria mapping (§4.C): mentah is the rejected share, tangkai panjang the
    long stalks among accepted bunches, matang the rest — AutoERP derives that
    last one itself. `detail_url` is deliberately not sent (see
    `../docs/PROGRESS-AUTOGRADE-AUTOERP.md` §"Beda dari rancangan Mas Samuel").
    """
    total = int(grading.get("total") or 0)
    counts = {
        "total": total,
        "acc": int(grading.get("acc") or 0),
        "rej": int(grading.get("rej") or 0),
        "mentah": int(grading.get("rej") or 0),
        "tangkai_panjang": int(grading.get("tangkai_panjang") or 0),
        "manual_reject": int(grading.get("manual_reject") or 0),
    }
    return {
        "assignment_id": grading.get("assignment_id"),
        "line_code": grading.get("line_code"),
        "started_at": grading.get("mulai"),
        "ended_at": grading.get("selesai"),
        "counts": counts,
        "pct": {
            "mentah": _share(counts["mentah"], total),
            "tangkai_panjang": _share(counts["tangkai_panjang"], total),
        },
    }


def _share(count: int, total: int) -> float:
    """Percent of the bunches graded. An assignment that graded nothing is 0."""
    return round(count / total * 100, 2) if total else 0.0
