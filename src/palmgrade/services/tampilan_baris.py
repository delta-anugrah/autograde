"""How a console row is shown: source label, photo URLs, ticket and assignment views.

Moved out of `services/console_service.py` (batch 5.12) so that module stays under 1,000
lines (`tests/unit/test_ukuran_berkas.py`). Pure shaping of rows the store returned: no I/O.
"""
from __future__ import annotations

from typing import Any

from ..domain.capture_layout import thumb_key_of
from ..domain.ffb_source import ffb_source_label
from ..domain.gerbang import durasi_kunjungan, tahap_tiket
from ..domain.jawaban_kunjungan import golongkan


def _source_label(row: dict[str, Any]) -> str | None:
    """Label from the store's source facts, popped so they never reach the API."""
    return ffb_source_label(
        has_supplier=bool(row.pop("has_supplier", 0)),
        in_erp=bool(row.pop("in_erp", 0)),
    )


def _with_source_label(row: dict[str, Any]) -> dict[str, Any]:
    """Replace the source facts with the display label (§3.5b).

    Pop first, then assign: `{**row, ...}` evaluates before `pop`, and that
    once leaked raw columns into the API response.
    """
    row["source_label"] = _source_label(row)
    return row


def _tiket_view(row: dict[str, Any]) -> dict[str, Any]:
    """One Timbangan row: the source label, and whether AutoERP's last answer for this
    visit needs a human (batch 2.3), the queue and total minutes and the stage (standard L4).
    Computed here so the screen never parses AutoERP's sentences or adds up clocks."""
    row["erp_perlu_dicek"] = golongkan(row.get("erp_note"))
    row.update(durasi_kunjungan(row), tahap=tahap_tiket(row))
    return _with_source_label(row)


def _assignment_view(row: dict[str, Any] | None) -> dict[str, Any] | None:
    # A row with an empty truck_id = truck already released. The row stays on
    # purpose (the line's assignment history), but the screen must say "none".
    if not row or not row.get("truck_id"):
        return None
    return {
        "assignment_id": row["assignment_id"],
        "truck_id": row["truck_id"],
        "plate_number": row.get("plate_number"),
        "supplier_name": row.get("supplier_name"),
        "source_label": _source_label(row),
    }


def _with_foto(row: dict[str, Any]) -> dict[str, Any]:
    """`image_url` (full size, for the photo dialog) and `thumb_url` (the 400 px copy the
    line writes beside it, for tables; batch 5.12). No small copy for a photo written before
    the bbox/clean/thumb layout: `thumb_url` is None and the screen uses the full one."""
    row["image_url"] = _capture_url(row.get("line_code"), row.get("image_path"))
    row["thumb_url"] = thumb_key_of(row["image_url"]) if row["image_url"] else None
    return row


def _capture_url(line_code: str | None, image_path: str | None) -> str | None:
    """Mirrors `resolveCaptureUrl` in palmgrade-api — the shape must match.

    Absolute URLs (R2, from the batch upload lane) pass through as-is.
    """
    if image_path and image_path.lower().startswith(("http://", "https://")):
        return image_path
    if not image_path or not line_code:
        return None
    rel = image_path.lstrip("/").removeprefix("captures/").lstrip("/")
    return f"/captures/{line_code}/{rel}"
