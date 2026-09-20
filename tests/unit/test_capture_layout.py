"""Where a capture image is filed inside its day folder.

The layout exists to be read by people: an operator asked for "the truck that
tipped around 9 this morning" must find it without opening the console, and the
folder is the label an AI training run consumes (`Ripe/`, `Unripe/`, `JK/` are
the classes, with `Ripe/TP/` one level deeper). Everything asserted here
protects one of those two readers.

The JSON sidecar is deliberately NOT covered by this module — it stays flat in
the day folder because `BatchUploadWorker._scan()` globs `*/*_ripeness.json`,
a fixed two-level depth. Moving it would silence the cloud upload with no error
at all; `test_batch_upload_worker.py` guards that from the other side.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from palmgrade.domain.capture_layout import (
    UNASSIGNED_FOLDER,
    CaptureVariant,
    build_r2_key,
    clean_twin_of,
    image_relative_path,
    thumb_key_of,
    thumb_twin_of,
    truck_folder_name,
    twins_of,
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
    "variant,grade_class,expected",
    [
        (CaptureVariant.ANNOTATED, "Ripe", "bbox/Ripe"),
        (CaptureVariant.ANNOTATED, "Unripe", "bbox/Unripe"),
        (CaptureVariant.CLEAN, "JK", "clean/JK"),
        (CaptureVariant.CLEAN, "Unripe", "clean/Unripe"),
    ],
)
def test_variant_and_class_each_get_a_folder(
    variant: CaptureVariant, grade_class: str, expected: str
) -> None:
    """`clean/Unripe` is a ready-made training set: no JSON parsing needed."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="091432_B1234XY_a3f9c201",
        variant=variant,
        grade_class=grade_class,
        filename="2026-09-08_021432_781225_auto.webp",
    )

    assert path == (
        f"2026-09-08/091432_B1234XY_a3f9c201/{expected}/"
        "2026-09-08_021432_781225_auto.webp"
    )


def test_the_class_folder_keeps_the_model_casing() -> None:
    """`Ripe`, not `ripe`. The folder must match `grade_class` in the sidecar and
    in SQLite exactly, or a training run that trusts the folder and a recap that
    trusts the field disagree about the same bunch — and neither says so."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="t",
        variant=CaptureVariant.CLEAN,
        grade_class="Ripe",
        filename="f.webp",
    )

    assert path == "2026-09-08/t/clean/Ripe/f.webp"


def test_an_unknown_class_is_filed_rather_than_dropped() -> None:
    """A new model class must not cost us the image."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="t",
        variant=CaptureVariant.ANNOTATED,
        grade_class="Sesuatu",
        filename="f.webp",
    )

    assert path == "2026-09-08/t/bbox/Sesuatu/f.webp"


def test_both_variants_share_one_filename() -> None:
    """The pairing is the filename, so no index is needed to find the twin —
    and `event_id` (uuid5 of that name) is untouched by this whole change.
    """
    common = dict(
        date_folder="2026-09-08",
        truck_folder="091432_B1234XY_a3f9c201",
        grade_class="Ripe",
        filename="2026-09-08_021432_781225_auto.webp",
    )

    annotated = image_relative_path(variant=CaptureVariant.ANNOTATED, **common)
    clean = image_relative_path(variant=CaptureVariant.CLEAN, **common)

    assert annotated.rsplit("/", 1)[-1] == clean.rsplit("/", 1)[-1]
    assert annotated != clean


# ----------------------------------------------------------------- image twins


ANNOTATED = Path("/r/2026-09-08/091432_B1234XY_a3f9c201/bbox/acc/x.webp")


def test_twins_are_the_clean_and_thumb_copies() -> None:
    root = Path("/r/2026-09-08/091432_B1234XY_a3f9c201")
    assert twins_of(ANNOTATED) == [root / "clean/acc/x.webp", root / "thumb/acc/x.webp"]
    assert clean_twin_of(ANNOTATED) == [root / "clean/acc/x.webp"]
    assert thumb_twin_of(ANNOTATED) == root / "thumb/acc/x.webp"


def test_a_flat_capture_has_no_twins() -> None:
    flat = Path("/r/2026-09-08/x.webp")
    assert twins_of(flat) == []
    assert thumb_twin_of(flat) is None


def test_thumb_key_swaps_only_the_variant_segment() -> None:
    assert thumb_key_of("M1/results/2026-09-08/T/bbox/acc/x.webp") == "M1/results/2026-09-08/T/thumb/acc/x.webp"
    assert thumb_key_of("M1/results/2026-09-08/x.webp") is None


def test_r2_key_is_machine_then_path_without_captures_prefix() -> None:
    assert build_r2_key("M1", "captures/results/2026-09-08/T/bbox/acc/x.webp") == "M1/results/2026-09-08/T/bbox/acc/x.webp"


# ------------------------------------------------- folder kelas + subfolder TP
#
# Sejak model 4 kelas, folder verdict (`acc`/`rej`) diganti folder KELAS
# (`Ripe`/`Unripe`/`JK`): `clean/` adalah training set, dan Unripe vs JK yang
# sudah bisa dibedakan model tidak boleh dilebur lagi jadi satu folder `rej/`.
# Ripe yang bertangkai panjang turun satu level lagi ke `Ripe/TP/`, supaya
# mencari hasil TP cukup membuka satu folder.


def test_kelas_model_jadi_nama_folder() -> None:
    """`Ripe`/`Unripe`/`JK`, bukan lagi `acc`/`rej`."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="091432_B1234XY_a3f9c201",
        variant=CaptureVariant.CLEAN,
        grade_class="Unripe",
        filename="f.webp",
    )

    assert path == "2026-09-08/091432_B1234XY_a3f9c201/clean/Unripe/f.webp"


def test_ripe_bertangkai_panjang_turun_ke_subfolder_tp() -> None:
    """Satu folder untuk semua hasil TP — itu seluruh alasan sub-folder ini ada."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="t",
        variant=CaptureVariant.ANNOTATED,
        grade_class="Ripe",
        tp=True,
        filename="f.webp",
    )

    assert path == "2026-09-08/t/bbox/Ripe/TP/f.webp"


def test_kelas_selain_ripe_tidak_pernah_punya_subfolder_tp() -> None:
    """TP cuma dicek untuk Ripe (keputusan 2026-09-20): REJ dibuang piston, jadi
    tangkainya tidak dibayar dan tidak perlu dicatat. `tp=True` pada kelas REJ
    adalah pemanggil yang keliru — path-nya tetap tanpa `TP/`, bukan dilempar,
    supaya satu pemanggil salah tidak membuang gambarnya."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="t",
        variant=CaptureVariant.CLEAN,
        grade_class="Unripe",
        tp=True,
        filename="f.webp",
    )

    assert path == "2026-09-08/t/clean/Unripe/f.webp"


def test_kelas_kosong_tetap_difiling_bukan_dibuang() -> None:
    """Capture manual tidak pernah lewat model, jadi kelasnya memang tidak ada.
    Gambarnya tetap harus punya tempat — aturan yang sama dengan verdict asing
    sebelum perubahan ini."""
    path = image_relative_path(
        date_folder="2026-09-08",
        truck_folder="t",
        variant=CaptureVariant.ANNOTATED,
        grade_class=None,
        filename="f.webp",
    )

    assert path == "2026-09-08/t/bbox/unknown/f.webp"


# Kembaran harus tetap ketemu walau path-nya satu level lebih dalam. Ini yang
# paling mahal kalau salah: clean & thumb tidak punya baris manifest sendiri,
# jadi kembaran yang tidak ketemu berarti tidak ada apa pun lagi yang
# menghapusnya — disk penuh diam-diam, lalu grading berhenti menyimpan.

TP_ANNOTATED = Path("/r/2026-09-08/091432_B1234XY_a3f9c201/bbox/Ripe/TP/x.webp")


def test_kembaran_tp_ketemu_walau_satu_level_lebih_dalam() -> None:
    root = Path("/r/2026-09-08/091432_B1234XY_a3f9c201")
    assert twins_of(TP_ANNOTATED) == [
        root / "clean/Ripe/TP/x.webp",
        root / "thumb/Ripe/TP/x.webp",
    ]
    assert thumb_twin_of(TP_ANNOTATED) == root / "thumb/Ripe/TP/x.webp"


def test_kunci_thumb_r2_dan_kembaran_lokal_sepakat_untuk_tp() -> None:
    """Dua fungsi, satu jawaban. `thumb_key_of` (kunci R2) memakai substring dan
    sudah benar untuk TP; kalau `thumb_twin_of` (berkas lokal) memakai aturan
    lain, yang satu menunjuk berkas yang tidak pernah diunggah yang lain."""
    key = build_r2_key("M1", "captures/results/2026-09-08/T/bbox/Ripe/TP/x.webp")

    assert thumb_key_of(key) == "M1/results/2026-09-08/T/thumb/Ripe/TP/x.webp"
    assert thumb_twin_of(Path("/r/2026-09-08/T/bbox/Ripe/TP/x.webp")) == Path(
        "/r/2026-09-08/T/thumb/Ripe/TP/x.webp"
    )
