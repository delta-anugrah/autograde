"""Where a capture image is filed inside its day folder.

    artifacts/results/2026-09-08/
      2026-09-08_021432_781225_auto_ripeness.json   <- stays FLAT, see below
      091432_B1234XY_a3f9c201/
        bbox/acc/    bbox/rej/                      <- annotated, the evidence
        clean/acc/   clean/rej/                     <- unannotated, for training
      _belum-assign/                                <- graded before a truck was set

Three rules hold this shape together, and each has already cost us something:

1. **The JSON sidecar never moves.** `BatchUploadWorker._scan()` finds work with
   `results.glob("*/*_ripeness.json")` — a fixed two-level depth. A sidecar one
   level deeper is simply never found, so the cloud upload stops with no error
   and nothing to notice. Only images live in the sub-tree; the uploader reads
   their location out of the JSON (`image_path`), never from where the JSON sits.

2. **Folder clocks are the mill's, filenames are UTC.** Filenames feed `event_id`
   (uuid5), so they must not move. Folder names are the one thing a human reads,
   and a 16:00 WIB truck filed as `090000` defeats the point of having them.
   Two zones in one tree is deliberate: folders for people, filenames for machines.

3. **The verdict is a folder, not a field.** `clean/acc` and `clean/rej` are a
   labelled training set that needs no JSON parsing.
"""
from __future__ import annotations

import datetime
import enum
import re
from pathlib import Path

from .plate import normalisasi_plat

# Named so it cannot be mistaken for a truck: if this folder has contents,
# someone graded bunches before assigning a truck. A truck folder always starts
# with a digit, so the underscore also groups these together in a file manager.
UNASSIGNED_FOLDER = "_belum-assign"

# Plates and assignment ids reach us as operator-typed text and as ERP payload
# fields. Anything outside this set is dropped rather than escaped — a path
# separator here would write outside the day folder.
_UNSAFE = re.compile(r"[^A-Za-z0-9]")

_SHORT_ASSIGNMENT_LEN = 8


class CaptureVariant(enum.Enum):
    """The two images kept per bunch.

    ANNOTATED is what the operator and any dispute look at. CLEAN is the raw
    frame: a model must never be retrained on pictures carrying its own
    predictions, so the training copy has to be the undrawn one.
    """

    ANNOTATED = "bbox"
    CLEAN = "clean"


def _sanitise(value: str) -> str:
    return _UNSAFE.sub("", value)


def truck_folder_name(
    started_at: datetime.datetime,
    *,
    plate: str | None,
    assignment_id: str | None,
    tz: datetime.tzinfo | None = None,
) -> str:
    """`091432_B1234XY_a3f9c201` — local time first, so a day sorts by clock.

    `started_at` is converted to `tz` (the mill zone, `FACTORY_TZ`) before the
    clock is read, so the same instant yields the same folder whether the caller
    held it as UTC or as local time. Without an assignment there is no truck to
    group under, so the bunch goes to `UNASSIGNED_FOLDER`.
    """
    if tz is not None and started_at.tzinfo is not None:
        started_at = started_at.astimezone(tz)
    short_assignment = _sanitise(assignment_id or "")[:_SHORT_ASSIGNMENT_LEN]
    if not short_assignment:
        return UNASSIGNED_FOLDER

    parts = [started_at.strftime("%H%M%S")]
    if plate:
        # Normalising means "B 1234 xy" and "b-1234-XY" land in one folder. A
        # plate too mangled to normalise is dropped: the assignment id below
        # still groups the visit correctly.
        try:
            parts.append(normalisasi_plat(plate))
        except Exception:  # noqa: BLE001 - any unusable plate, same handling
            pass
    parts.append(short_assignment)
    return "_".join(parts)


def image_relative_path(
    *,
    date_folder: str,
    truck_folder: str,
    variant: CaptureVariant,
    ripeness_status: str,
    filename: str,
) -> str:
    """Path of one image relative to `results/`, e.g.
    `2026-09-08/091432_B1234XY_a3f9c201/bbox/rej/<ts>_auto.webp`.

    An unrecognised verdict gets its own folder rather than being dropped: a new
    model class must not cost us the image.
    """
    verdict = _sanitise(ripeness_status).lower() or "unknown"
    return f"{date_folder}/{truck_folder}/{variant.value}/{verdict}/{filename}"


def clean_twin_of(annotated: Path) -> list[Path]:
    """The clean copy beside an annotated one, or nothing if there cannot be one.

    Retention deletes by path rather than by manifest row: the clean copy has no
    row of its own, and giving it one would mean a second upload state machine
    for a file that is never uploaded. Derived here so the pairing rule lives
    with the layout that creates it.

    Empty for a capture written before this layout existed (flat in the day
    folder) — those keep arriving in retention for a full retention period after
    an upgrade, and they simply have no twin.
    """
    if annotated.parent.parent.name != CaptureVariant.ANNOTATED.value:
        return []
    clean = annotated.parent.parent.parent / CaptureVariant.CLEAN.value
    return [clean / annotated.parent.name / annotated.name]
