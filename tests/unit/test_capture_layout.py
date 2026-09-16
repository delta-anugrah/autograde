"""Where a capture image is filed inside its day folder.

The layout exists to be read by people: an operator asked for "the truck that
tipped around 9 this morning" must find it without opening the console, and the
folder is the label an AI training run consumes (`acc/` and `rej/` are the
classes). Everything asserted here protects one of those two readers.

The JSON sidecar is deliberately NOT covered by this module — it stays flat in
the day folder because `BatchUploadWorker._scan()` globs `*/*_ripeness.json`,
a fixed two-level depth. Moving it would silence the cloud upload with no error
at all; `test_batch_upload_worker.py` guards that from the other side.
"""
from __future__ import annotations

import datetime
import re
from zoneinfo import ZoneInfo

import pytest

from palmgrade.domain.capture_layout import (
    UNASSIGNED_FOLDER,
    CaptureVariant,
    image_relative_path,
    truck_folder_name,
)

JAKARTA = ZoneInfo("Asia/Jakarta")
UTC = datetime.UTC


# --------------------------------------------------------------- truck folder


def test_folder_leads_with_the_local_time_so_a_day_sorts_chronologically() -> None:
    """Time first: the mill asks "which truck at 9am", never "which plate".

    Sorted listings are the only index anyone has on the factory PC.
    """
    started = datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA)

    name = truck_folder_name(started, plate="B1234XY", assignment_id="a3f9c201-dead-beef")

    assert name.startswith("091432_")


def test_folder_carries_plate_and_a_short_assignment_id() -> None:
    started = datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA)

    name = truck_folder_name(started, plate="B1234XY", assignment_id="a3f9c201-dead-beef")

    assert name == "091432_B1234XY_a3f9c201"


def test_the_clock_is_the_mill_zone_not_utc() -> None:
    """The regression this whole module exists to prevent.

    Filenames and `date_folder` stay UTC on purpose (event_id is derived from
    them). Folder names are the one place a human reads a clock, so a 16:00 WIB
    truck must not be filed as `090000`.
    """
    afternoon_in_jakarta = datetime.datetime(2026, 9, 8, 16, 0, 0, tzinfo=JAKARTA)

    name = truck_folder_name(
        afternoon_in_jakarta, plate="B1234XY", assignment_id="a3f9c201", tz=JAKARTA
    )

    assert name.startswith("160000_")
    # The same instant expressed in UTC must not change the answer — vision
    # holds its clock in UTC, so this is the shape the real caller passes.
    assert name == truck_folder_name(
        afternoon_in_jakarta.astimezone(UTC),
        plate="B1234XY",
        assignment_id="a3f9c201",
        tz=JAKARTA,
    )


def test_a_plate_is_normalised_so_one_truck_is_one_folder() -> None:
    """`B 1234 xy` retyped on another shift is the same truck, not a twin."""
    started = datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA)

    spaced = truck_folder_name(started, plate="B 1234 xy", assignment_id="a3f9c201")
    dashed = truck_folder_name(started, plate="b-1234-XY", assignment_id="a3f9c201")

    assert spaced == dashed == "091432_B1234XY_a3f9c201"


def test_folder_is_filesystem_safe() -> None:
    """A plate is operator-typed text; it must never escape the day folder."""
    started = datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA)

    name = truck_folder_name(started, plate="../../etc", assignment_id="a3f9/c201")

    assert "/" not in name and ".." not in name
    assert re.fullmatch(r"[A-Za-z0-9_]+", name)


def test_a_missing_plate_still_files_under_the_assignment() -> None:
    """Vision learns the plate from the console; an older console may not send
    one. Losing the grouping is worse than a less readable name.
    """
    started = datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA)

    name = truck_folder_name(started, plate=None, assignment_id="a3f9c201")

    assert name == "091432_a3f9c201"


def test_no_assignment_means_the_unassigned_folder() -> None:
    """Bunches keep being graded before the operator assigns a truck. They are
    still evidence, so they are filed — just visibly apart.
    """
    started = datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA)

    assert truck_folder_name(started, plate=None, assignment_id=None) == UNASSIGNED_FOLDER
    assert truck_folder_name(started, plate="B1234XY", assignment_id="") == UNASSIGNED_FOLDER


def test_the_unassigned_folder_never_collides_with_a_truck() -> None:
    """It must stand apart at a glance: if it has contents, someone graded
    before assigning a truck.

    Not a sort assertion — `_` is ASCII 95, so byte order puts it *after* the
    digits a truck folder starts with. What matters is that no truck name can
    ever produce it, so the two can never be confused.
    """
    started = datetime.datetime(2026, 9, 8, 0, 0, 1, tzinfo=JAKARTA)

    assert UNASSIGNED_FOLDER.startswith("_")
    assert not truck_folder_name(
        started, plate="A", assignment_id="b"
    ).startswith("_")


# ------------------------------------------------------------- image location


@pytest.mark.parametrize(
    "variant,status,expected",
    [
        (CaptureVariant.ANNOTATED, "acc", "bbox/acc"),
        (CaptureVariant.ANNOTATED, "rej", "bbox/rej"),
        (CaptureVariant.CLEAN, "acc", "clean/acc"),
        (CaptureVariant.CLEAN, "rej", "clean/rej"),
    ],
)
def test_variant_and_verdict_each_get_a_folder(
    variant: CaptureVariant, status: str, expected: str
) -> None:
    """`clean/acc` is a ready-made training set: no JSON parsing needed."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="091432_B1234XY_a3f9c201",
        variant=variant,
        ripeness_status=status,
        filename="2026-09-08_021432_781225_auto.webp",
    )

    assert path == (
        f"2026-09-08/091432_B1234XY_a3f9c201/{expected}/"
        "2026-09-08_021432_781225_auto.webp"
    )


def test_the_verdict_folder_is_case_insensitive() -> None:
    """The auto path lowercases its status, the manual path does not."""
    lower = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="t",
        variant=CaptureVariant.CLEAN,
        ripeness_status="rej",
        filename="f.webp",
    )
    upper = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="t",
        variant=CaptureVariant.CLEAN,
        ripeness_status="REJ",
        filename="f.webp",
    )

    assert lower == upper


def test_an_unknown_verdict_is_filed_rather_than_dropped() -> None:
    """A new model class must not cost us the image."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="t",
        variant=CaptureVariant.ANNOTATED,
        ripeness_status="unripe",
        filename="f.webp",
    )

    assert path == "2026-09-08/t/bbox/unripe/f.webp"


def test_both_variants_share_one_filename() -> None:
    """The pairing is the filename, so no index is needed to find the twin —
    and `event_id` (uuid5 of that name) is untouched by this whole change.
    """
    common = dict(
        date_folder="2026-09-08",
        truck_folder="091432_B1234XY_a3f9c201",
        ripeness_status="acc",
        filename="2026-09-08_021432_781225_auto.webp",
    )

    annotated = image_relative_path(variant=CaptureVariant.ANNOTATED, **common)
    clean = image_relative_path(variant=CaptureVariant.CLEAN, **common)

    assert annotated.rsplit("/", 1)[-1] == clean.rsplit("/", 1)[-1]
    assert annotated != clean
