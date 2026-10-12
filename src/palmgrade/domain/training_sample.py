"""Training photos for nexio: which photos are priority, what their manifest says, where they go.

Pure, no I/O (coding standard L2). The console builds a manifest when a bunch first
arrives (`services/training_inbox.py`); the uploader completes its `image` block once
it has read the photo (`workers/training_upload_worker.py`).

Contract `autograde-training-sample/v1`: nexio-vision-ai
docs/architecture/AUTOGRADE_TO_NEXIO_PIPELINE.md §4, frozen by
tests/fixtures/autograde-training-sample/v1/, which nexio's tests read byte for byte.
A field renamed here without a `v2` breaks nexio's import silently.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .capture_layout import clean_twin_of
from .grade_class import JK
from .vision_event import TP_PASS

SCHEMA = "autograde-training-sample/v1"
KEY_PREFIX = "v1"
RULE_VERSION = 1

MANUAL_REJECT = "MANUAL_REJECT"
LOW_CONFIDENCE = "LOW_CONFIDENCE"
RARE_CLASS = "RARE_CLASS"
REASONS = (MANUAL_REJECT, LOW_CONFIDENCE, RARE_CLASS)

SEND_ALL = "all"
SEND_PRIORITY = "priority"
SEND_MODES = (SEND_ALL, SEND_PRIORITY)

PHOTO_CONTENT_TYPE = "image/webp"
MANIFEST_CONTENT_TYPE = "application/json"

_RARE_CLASSES = frozenset({JK})
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_BOX_KEYS = ("x_min", "y_min", "x_max", "y_max")


def priority_reasons(
    *, capture_type: str, grade_class: str | None, confidence: float | None, tp_present: bool, low_confidence: float
) -> list[str]:
    """Why a reviewer should look at this photo first (spec §5). Empty = a normal photo.

    A manual reject is never also LOW_CONFIDENCE: its 1.0 is not a model's confidence.
    """
    reasons: list[str] = []
    if capture_type == "manual":
        reasons.append(MANUAL_REJECT)
    elif confidence is not None and confidence < low_confidence:
        reasons.append(LOW_CONFIDENCE)
    if grade_class in _RARE_CLASSES or tp_present:
        reasons.append(RARE_CLASS)
    return reasons


def folders_of(image_path: str | None) -> dict[str, str | None]:
    """AutoGrade's own day and truck folder names, read from the event's image path.

    `captures/results/<day>/<truck>/bbox/<Class>[/TP]/<file>`. A capture written before
    the per-truck layout (flat in the day folder) has a day and no truck.
    """
    parts = [p for p in (image_path or "").split("/") if p]
    if len(parts) < 4 or parts[0] != "captures" or parts[1] != "results":
        return {"day": None, "truck": None}
    truck = parts[3] if len(parts) >= 6 and parts[4] == "bbox" else None
    return {"day": parts[2], "truck": truck}


def _segment(value: str) -> str:
    """One key segment: safe characters only, and never empty or made only of dots."""
    cleaned = _UNSAFE_KEY_CHARS.sub("_", value)
    return "_" if set(cleaned) <= {"."} else cleaned


def normalise_captured_at(value: str) -> str:
    """The timestamp as nexio accepts it: with a UTC offset.

    One with an offset passes through untouched; a naive one is read as UTC and gets
    `+00:00`, so the manifest and the object key always agree on the day.
    """
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is not None:
        return value
    return moment.replace(tzinfo=UTC).isoformat()


def object_keys(machine_id: str, captured_at: str, event_id: str) -> tuple[str, str]:
    """(photo key, manifest key). The day is the UTC day of `captured_at`.

    nexio's validator checks the key's day against the UTC day of `captured_at`, so a
    timestamp without an offset is read as UTC rather than as the machine's local time.
    """
    day = datetime.fromisoformat(normalise_captured_at(captured_at)).astimezone(UTC).strftime("%Y-%m-%d")
    base = f"{KEY_PREFIX}/{_segment(machine_id)}/{day}/{_segment(event_id)}"
    return f"{base}.webp", f"{base}.json"


def _box(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict) or any(raw.get(k) is None for k in _BOX_KEYS):
        return None
    box = {k: int(raw[k]) for k in _BOX_KEYS}
    if box["x_min"] >= box["x_max"] or box["y_min"] >= box["y_max"]:
        return None
    return box


def _prediction(payload: dict[str, Any], *, tp_present: bool) -> dict[str, Any] | None:
    if str(payload.get("capture_type") or "auto") == "manual":
        return None
    tp = None
    if tp_present:
        tp = {"present": True, "confidence": payload.get("tp_confidence"), "box": _box(payload.get("tp_bounding_box"))}
    return {
        "class": payload.get("grade_class"),
        "confidence": payload.get("ripeness_confidence"),
        "bunch_box": _box(payload.get("bounding_box")),
        "tp": tp,
    }


def build_manifest(
    payload: dict[str, Any],
    *,
    line_code: str | None,
    plate: str | None,
    company: str,
    autograde_version: str,
    low_confidence: float,
) -> dict[str, Any]:
    """The manifest for one ingested event, without its `image` block (see `with_image`)."""
    capture_type = str(payload.get("capture_type") or "auto")
    tp_present = payload.get("tp_status") == TP_PASS
    reasons = priority_reasons(
        capture_type=capture_type,
        grade_class=payload.get("grade_class"),
        confidence=payload.get("ripeness_confidence"),
        tp_present=tp_present,
        low_confidence=low_confidence,
    )
    return {
        "schema": SCHEMA,
        "event_id": str(payload["event_id"]),
        "captured_at": normalise_captured_at(str(payload["timestamp"])),
        "capture_type": capture_type,
        "folder": folders_of(payload.get("image_path")),
        "source": {
            "company": company or None,
            "machine_id": str(payload["machine_id"]),
            "line_code": line_code,
            "autograde_version": autograde_version or None,
            "model_file": payload.get("model_file") or None,
        },
        "visit": {
            "truck_id": payload.get("truck_id"),
            "assignment_id": payload.get("assignment_id"),
            "plate": plate,
        },
        "prediction": _prediction(payload, tp_present=tp_present),
        "priority": {"reasons": reasons, "rule_version": RULE_VERSION},
    }


def with_image(manifest: dict[str, Any], *, sha256: str, size: int) -> dict[str, Any]:
    """The manifest as uploaded: the photo's key, checksum and size, known only once it is read."""
    photo_key, _ = object_keys(manifest["source"]["machine_id"], manifest["captured_at"], manifest["event_id"])
    return {
        **manifest,
        "image": {"key": photo_key, "sha256": sha256, "bytes": size, "content_type": PHOTO_CONTENT_TYPE},
    }


def photo_path(artifacts_dir: Path, line_code: str, image_path: str | None) -> Path | None:
    """The `clean/` copy of an event's photo under the console's read-only line mount.

    Same root as the `/captures/<line>` mount in console_main.py. None when the event
    has no path or was written flat (before the bbox/clean layout): no clean twin exists.
    """
    if not image_path or image_path.lower().startswith(("http://", "https://")):
        return None
    if not line_code or any(c in line_code for c in "/\\") or ".." in line_code:
        return None
    relative = image_path.lstrip("/").removeprefix("captures/").lstrip("/")
    # Pure check, no filesystem: an event's path is data from a line, never trusted to stay in the mount.
    if ".." in relative.replace("\\", "/").split("/"):
        return None
    twins = clean_twin_of(artifacts_dir / line_code / relative)
    return twins[0] if twins else None
