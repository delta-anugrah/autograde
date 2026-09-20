"""Where a capture image is filed inside its day folder.

    artifacts/results/2026-09-08/
      2026-09-08_021432_781225_auto_ripeness.json   <- stays FLAT, see below
      091432_B1234XY_a3f9c201/
        bbox/Ripe/   bbox/Ripe/TP/   bbox/Unripe/   bbox/JK/   <- annotated, the evidence
        clean/Ripe/  clean/Ripe/TP/  clean/Unripe/  clean/JK/  <- unannotated, for training
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

3. **The class is a folder, not a field.** `clean/Ripe` and `clean/Unripe` are a
   labelled training set that needs no JSON parsing. Class, not verdict, since
   2026-09-20: `acc`/`rej` folders re-merged Unripe and JK, discarding exactly
   what the 4-class retrain bought. `Ripe/TP/` sits one level deeper, so no
   reader may assume a fixed depth — see `_twin`.
"""
from __future__ import annotations

import datetime
import enum
import re
from pathlib import Path

from .grade_class import RIPE
from .plate import normalisasi_plat

# Sub-folder for a Ripe bunch that carries a long stalk. A folder rather than a
# filename marker so that "show me every TP result" is one folder, which is the
# reason it exists at all (decided 2026-09-20).
TP_FOLDER = "TP"

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
    """The three images kept per bunch.

    ANNOTATED is what the operator and any dispute look at. CLEAN is the raw
    frame: a model must never be retrained on pictures carrying its own
    predictions, so the training copy has to be the undrawn one.
    Same picture as ANNOTATED, 400 px wide: what the backoffice grid loads.
    Full size is one click away; 500 of these is 7 MB, 500 full ones is 90.
    """

    ANNOTATED = "bbox"
    CLEAN = "clean"
    THUMB = "thumb"


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
    grade_class: str | None,
    filename: str,
    tp: bool = False,
) -> str:
    """Path of one image relative to `results/`, e.g.
    `2026-09-08/091432_B1234XY_a3f9c201/bbox/Unripe/<ts>_auto.webp`.

    The folder is the model CLASS, not the binary verdict (changed 2026-09-20).
    `clean/` is a training set, and `Unripe` and `JK` — which the model already
    tells apart — used to be melted back into one `rej/` folder, throwing away
    the very distinction the 4-class model was retrained for.

    A `Ripe` bunch with a long stalk goes one level deeper, into `Ripe/TP/`: the
    whole point of the sub-folder is that finding every TP result is opening one
    folder. `tp` is ignored for every other class — TP is only looked for on Ripe
    (decided 2026-09-20), so a `tp=True` on a REJ class is a mistaken caller, and
    filing the image anyway beats losing it over a caller's bug.

    An unusable class gets `unknown/` rather than being dropped: a manual capture
    never went through the model, so it genuinely has no class.
    """
    kelas = _sanitise(grade_class or "") or "unknown"
    ekor = f"/{TP_FOLDER}" if tp and kelas == RIPE else ""
    return f"{date_folder}/{truck_folder}/{variant.value}/{kelas}{ekor}/{filename}"


def build_r2_key(machine_id: str, image_path: str) -> str:
    """Object key in R2: deterministic from the path, so a re-upload overwrites itself."""
    relative = image_path.lstrip("/").removeprefix("captures/")
    return f"{machine_id}/{relative}"


def _twin(annotated: Path, variant: CaptureVariant) -> Path | None:
    """Swap the `bbox` segment for another variant's, keeping everything after it.

    Depth-agnostic on purpose: `bbox/Ripe/TP/x.webp` is one level deeper than
    `bbox/Unripe/x.webp`, and the old rule — "the verdict sits exactly one level
    under bbox" — returned None for the deeper one. That failure is silent and
    expensive: the clean and thumb copies have no manifest row of their own, so a
    twin that is not found is a twin nothing else will ever delete, and the disk
    fills until `write_image` raises and grading stops saving (Rule #8/#9).

    Matches `thumb_key_of`, which already worked this way on the R2 key. Two
    rules for one pairing meant the remote key could name a file the local side
    never uploaded.
    """
    parts = annotated.parts
    try:
        i = len(parts) - 1 - parts[::-1].index(CaptureVariant.ANNOTATED.value)
    except ValueError:
        return None  # written before this layout existed (flat in the day folder)
    return Path(*parts[:i], variant.value, *parts[i + 1 :])


def twins_of(annotated: Path) -> list[Path]:
    """Every sibling copy of one annotated image: what retention must delete with it."""
    return [p for v in (CaptureVariant.CLEAN, CaptureVariant.THUMB) if (p := _twin(annotated, v))]


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
    clean = _twin(annotated, CaptureVariant.CLEAN)
    return [clean] if clean else []


def thumb_twin_of(annotated: Path) -> Path | None:
    return _twin(annotated, CaptureVariant.THUMB)


def thumb_key_of(r2_key: str) -> str | None:
    """R2 key of the thumbnail beside an annotated key; None for a flat (old) key."""
    marker = f"/{CaptureVariant.ANNOTATED.value}/"
    if marker not in r2_key:
        return None
    return r2_key.replace(marker, f"/{CaptureVariant.THUMB.value}/", 1)
