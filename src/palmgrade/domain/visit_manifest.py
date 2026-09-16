"""One JSON per truck visit, for the backoffice to open from the ERP ticket.

AutoERP gets the recap and a link (`detail_url`); this is what the link opens.
Pure: rows in, dict out. The console's manifest worker uploads it to R2 under
`manifest_key()`, and `static/viewer.html` renders it.

Every URL is derived, never stored: the R2 key of a bunch is a pure function
of `machine_id` and `image_path` (`capture_layout.build_r2_key`), so the
manifest can be written before the hourly image upload has run.
"""
from __future__ import annotations

from typing import Any

from .capture_layout import build_r2_key, thumb_key_of

MANIFEST_KIND = "manifest"
VIEWER_KEY = "viewer.html"
SCHEMA = 1
# Mirrors `ConsoleStore.grading_counts()` — a bunch must agree with its recap.
TP_THRESHOLD = 0.8


def manifest_key(visit_id: str) -> str:
    return f"visits/{visit_id}.json"


def detail_url_for(public_url: str, visit_id: str) -> str:
    return f"{public_url.rstrip('/')}/{VIEWER_KEY}?visit={visit_id}"


def _urls(public_url: str, row: dict[str, Any]) -> tuple[str | None, str | None]:
    if not row.get("image_path"):
        return None, None
    key = build_r2_key(row["machine_id"], row["image_path"])
    thumb = thumb_key_of(key)
    return f"{public_url}/{key}", f"{public_url}/{thumb}" if thumb else None


def _bunch(public_url: str, row: dict[str, Any]) -> dict[str, Any]:
    image, thumb = _urls(public_url, row)
    tp = row.get("tp_confidence")
    return {
        "event_id": row["event_id"],
        "timestamp": row["timestamp"],
        "verdict": row["ripeness_status"],
        "grade_class": row.get("grade_class"),
        "confidence": row.get("ripeness_confidence"),
        "tangkai_panjang": row["ripeness_status"] == "ACC" and tp is not None and tp > TP_THRESHOLD,
        "capture_type": row.get("capture_type"),
        "image": image,
        "thumb": thumb,
    }


def build_manifest(
    visit: dict[str, Any],
    grading: dict[str, Any],
    bunches: list[dict[str, Any]],
    *,
    public_url: str,
    generated_at: str,
) -> dict[str, Any]:
    public_url = public_url.rstrip("/")
    return {
        "schema": SCHEMA,
        "visit_id": visit["id"],
        "assignment_id": grading["assignment_id"],
        "line_code": grading.get("line_code"),
        "plate_number": visit.get("plate_number"),
        "supplier_name": visit.get("supplier_name"),
        "work_date": visit.get("work_date"),
        "started_at": grading.get("started_at"),
        "ended_at": grading.get("ended_at"),
        "generated_at": generated_at,
        "counts": {k: int(grading.get(k) or 0) for k in ("total", "acc", "rej", "tangkai_panjang", "manual_reject")},
        "bunches": [_bunch(public_url, row) for row in bunches],
    }
