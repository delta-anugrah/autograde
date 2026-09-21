"""Both save paths file images per truck, and keep a clean copy.

`FrameProcessingWorker` (auto) and `CaptureRepository` (manual reject) are the
only two writers of capture images, and they must agree: one layout, one place
that decides it (`domain/capture_layout.py`).

Two properties are load-bearing well beyond this module:

* the JSON sidecar stays flat in the day folder, or `BatchUploadWorker._scan()`
  stops finding work and the cloud upload dies silently;
* `image_path` in that JSON keeps pointing at the annotated image, because it is
  what palmgrade-api serves and what the R2 key is built from.

These run without torch or cv2: the worker is exercised through its save helper
with a stubbed storage, which is also what keeps the suite CI-light.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.capture_layout import UNASSIGNED_FOLDER

JAKARTA = ZoneInfo("Asia/Jakarta")


class RecordingStorage:
    """Stands in for `LocalFileStorage` — records instead of touching the disk."""

    def __init__(self) -> None:
        self.images: dict[str, object] = {}
        self.json: dict[str, dict] = {}
        self.thumbs: dict[str, object] = {}

    def write_image(self, path: Path, frame, quality: int = 80) -> None:
        self.images[str(path)] = frame

    def write_json(self, path: Path, payload: dict) -> None:
        self.json[str(path)] = payload

    def write_thumbnail(self, path: Path, frame, *, max_width: int, quality: int) -> None:
        self.thumbs[str(path)] = (frame, max_width, quality)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")


@pytest.fixture
def storage() -> RecordingStorage:
    return RecordingStorage()


def _relative(paths, results_dir: Path) -> set[str]:
    return {str(Path(p).relative_to(results_dir)) for p in paths}


# ------------------------------------------------------------------ auto path


# 09:14:32 WIB — sengaja jam yang BERBEDA jamnya di UTC, supaya folder yang
# keliru distempel UTC langsung terlihat.
ASSIGNED_AT = datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA)


class _OutboxDiam:
    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        pass


@pytest.fixture
def worker(settings, storage):
    """Penulis bukti yang sebenarnya, dengan storage di-stub.

    Diuji lewat `CaptureSaveWorker.run_once`, bukan lewat `FrameProcessingWorker`:
    jalur simpan pindah ke thread penulis pada 2026-09-18, dan helper lama di
    worker deteksi tinggal bangkai yang tidak dipanggil siapa pun — diuji
    berbulan-bulan sesudah berhenti dipakai produksi. Dihapus 2026-09-20.
    """
    from palmgrade.workers.capture_save_worker import CaptureSaveWorker

    return CaptureSaveWorker(settings=settings, storage=storage, outbox_store=_OutboxDiam())


def _job(**over):
    """Satu janjang, sebagaimana thread deteksi menyerahkannya."""
    from palmgrade.workers.capture_save_worker import SaveJob

    return SaveJob(**{
        "timestamp": "2026-09-08_021432_781225",
        "date_folder": "2026-09-08",
        "truck_folder": _truck_folder(),
        "annotated_frame": "ANNOTATED",
        "clean_frame": "CLEAN",
        "ripeness_status": "rej",
        "ripeness_conf": 0.91,
        "grade_class": "Unripe",
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        "truck_id": "truck-1",
        "assignment_id": "a3f9c201-dead-beef",
        "ffb_source": "External",
        "event_ts": "2026-09-08T02:14:32+00:00",
        "tp": None,
    } | over)


def _truck_folder(assignment_id: str | None = "a3f9c201-dead-beef",
                  plate: str | None = "B 1234 XY",
                  assigned_at: datetime.datetime | None = ASSIGNED_AT) -> str:
    """Nama folder truk lewat aturan resmi, bukan string rakitan tangan."""
    from palmgrade.domain.capture_layout import truck_folder_name

    return truck_folder_name(
        assigned_at or datetime.datetime(2026, 9, 8, 2, 14, 32, tzinfo=datetime.UTC),
        plate=plate,
        assignment_id=assignment_id,
        tz=JAKARTA,
    )


def test_auto_writes_both_variants_under_the_truck(worker, storage, settings):
    worker.run_once(_job(
        annotated_frame="ANNOTATED",
        clean_frame="CLEAN",
        ripeness_status="rej",
        grade_class="Unripe",
        ripeness_conf=0.91,
        truck_id="truck-1",
    ))

    written = _relative(storage.images, settings.results_dir)
    assert len(written) == 2
    truck = "091432_B1234XY_a3f9c201"
    assert any(f"/{truck}/bbox/Unripe/" in p for p in written)
    assert any(f"/{truck}/clean/Unripe/" in p for p in written)


def test_the_clean_copy_is_the_undrawn_frame(worker, storage):
    """A model retrained on its own boxes learns from its own answers."""
    worker.run_once(_job(
        annotated_frame="ANNOTATED",
        clean_frame="CLEAN",
        ripeness_status="acc",
        grade_class="Ripe",
        ripeness_conf=0.9,
        truck_id="truck-1",
        bounding_box={},
    ))

    by_variant = {
        "bbox" if "/bbox/" in path else "clean": frame
        for path, frame in storage.images.items()
    }
    assert by_variant == {"bbox": "ANNOTATED", "clean": "CLEAN"}


def test_both_variants_share_one_filename(worker, storage):
    names = {Path(p).name for p in storage.images} if storage.images else set()
    worker.run_once(_job(
        annotated_frame="A",
        clean_frame="C",
        ripeness_status="acc",
        grade_class="Ripe",
        ripeness_conf=0.9,
        truck_id="truck-1",
        bounding_box={},
    ))
    names = {Path(p).name for p in storage.images}

    assert len(names) == 1, "the pair must be findable by name alone"


def test_the_sidecar_stays_flat_in_the_day_folder(worker, storage, settings):
    """`BatchUploadWorker._scan()` globs `*/*_ripeness.json` — a fixed depth.

    One level deeper and the cloud upload finds nothing, with no error anywhere.
    """
    worker.run_once(_job(
        annotated_frame="A",
        clean_frame="C",
        ripeness_status="acc",
        grade_class="Ripe",
        ripeness_conf=0.9,
        truck_id="truck-1",
        bounding_box={},
    ))

    (sidecar,) = _relative(storage.json, settings.results_dir)
    assert sidecar.count("/") == 1, f"sidecar must sit directly in the day folder: {sidecar}"
    assert sidecar.endswith("_auto_ripeness.json")


def test_image_path_points_at_the_annotated_copy(worker, storage):
    """It is what palmgrade-api serves and what the R2 key is built from."""
    worker.run_once(_job(
        annotated_frame="A",
        clean_frame="C",
        ripeness_status="rej",
        grade_class="Unripe",
        ripeness_conf=0.9,
        truck_id="truck-1",
        bounding_box={},
    ))

    (meta,) = storage.json.values()
    assert meta["image_path"].startswith("captures/results/")
    assert "/bbox/Unripe/" in meta["image_path"]
    assert "/clean/" not in meta["image_path"]


def test_the_folder_clock_is_mill_local_not_utc(worker, storage):
    """09:14 WIB is 02:14 UTC. Filed as `021432` the folder is unfindable."""
    worker.run_once(_job(
        annotated_frame="A",
        clean_frame="C",
        ripeness_status="acc",
        grade_class="Ripe",
        ripeness_conf=0.9,
        truck_id="truck-1",
        bounding_box={},
    ))

    assert any("/091432_" in path for path in storage.images)


def test_bunches_graded_before_an_assignment_are_still_kept(worker, storage, settings):
    worker.run_once(_job(
        truck_folder=_truck_folder(assignment_id=None, plate=None, assigned_at=None),
        annotated_frame="A",
        clean_frame="C",
        ripeness_status="acc",
        grade_class="Ripe",
        ripeness_conf=0.9,
        truck_id=None,
        bounding_box={},
    ))

    assert storage.images, "an unassigned bunch is still evidence"
    assert all(f"/{UNASSIGNED_FOLDER}/" in path for path in storage.images)


def test_a_missing_assigned_at_does_not_lose_the_capture(worker, storage):
    """An older console sends no `assigned_at`; grading must not stop for it."""
    worker.run_once(_job(
        truck_folder=_truck_folder(assigned_at=None),
        annotated_frame="A",
        clean_frame="C",
        ripeness_status="acc",
        grade_class="Ripe",
        ripeness_conf=0.9,
        truck_id="truck-1",
        bounding_box={},
    ))

    assert len(storage.images) == 2


# ---------------------------------------------------------------- manual path


def test_manual_reject_uses_the_same_layout(settings, storage):
    """Two writers, one layout — or the folder means different things per line."""
    from palmgrade.repositories.capture_repository import CaptureRepository

    repo = CaptureRepository(settings, storage)

    result = repo.save_manual_reject(
        frame=_tiny_frame(),
        truck_id="truck-1",
        assignment_id="a3f9c201-dead-beef",
        plate="B 1234 XY",
        assigned_at=datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA).isoformat(),
    )

    written = _relative(storage.images, settings.results_dir)
    truck = "091432_B1234XY_a3f9c201"
    # `unknown/`: capture manual tidak pernah lewat model, jadi kelasnya memang
    # tidak ada — dan meminjam kelas yang tidak pernah diberikan akan mencemari
    # folder latih dengan gambar yang labelnya karangan.
    assert any(f"/{truck}/bbox/unknown/" in p for p in written)
    assert any(f"/{truck}/clean/unknown/" in p for p in written)
    assert "/bbox/unknown/" in result["image_url"]

    (sidecar,) = _relative(storage.json, settings.results_dir)
    assert sidecar.count("/") == 1, "manual sidecars stay flat too"


def test_manual_reject_without_a_console_still_saves(settings, storage):
    """The legacy `/api/capture_reject` route passes no assignment at all."""
    from palmgrade.repositories.capture_repository import CaptureRepository

    result = CaptureRepository(settings, storage).save_manual_reject(
        frame=_tiny_frame(), truck_id=None, assignment_id=None
    )

    assert len(storage.images) == 2
    assert f"/{UNASSIGNED_FOLDER}/" in result["image_url"]


class _Frame:
    """Stands in for a numpy frame.

    The repository only forwards the frame to storage and reads `.shape`, and
    storage is stubbed here — so a real array would pull numpy into a suite that
    runs without it on purpose (CLAUDE.md § Tests). The real encode is covered
    against actual numpy and cv2 in `tests/e2e/test_capture_folder_layout.py`.
    """

    shape = (4, 4, 3)


def _tiny_frame():
    return _Frame()


# ------------------------------------------------------- payload compatibility


def test_the_sidecar_still_carries_every_field_the_uploader_reads(worker, storage):
    """Guards the contract in CLAUDE.md § Integration Contracts."""
    worker.run_once(_job(
        annotated_frame="A",
        clean_frame="C",
        ripeness_status="rej",
        grade_class="Unripe",
        ripeness_conf=0.91,
        truck_id="truck-1",
    ))

    (meta,) = storage.json.values()
    for field in (
        "timestamp",
        "image_path",
        "ripeness_status",
        "ripeness_confidence",
        "capture_type",
        "truck_id",
        "bounding_box",
    ):
        assert field in meta, f"BatchUploadWorker reads {field}"
    # Serialisable: it is written to disk as JSON and read back hours later.
    json.dumps(meta)


# -------------------------------------------------- thumbnail


def _pair(writer, **over):
    return writer.write_pair(**{
        "date_folder": "2026-09-08", "truck_folder": "091432_B1234XY_a3f9c201",
        "grade_class": "Ripe", "filename": "x.webp",
        "annotated_frame": "ANNOTATED", "clean_frame": "CLEAN",
    } | over)


def test_write_pair_also_writes_a_400px_thumbnail_of_the_annotated_frame(settings, storage):
    from palmgrade.services.capture_writer import CaptureWriter

    _pair(CaptureWriter(settings, storage))
    [(path, (frame, width, quality))] = storage.thumbs.items()
    assert str(Path(path).relative_to(settings.results_dir)) == "2026-09-08/091432_B1234XY_a3f9c201/thumb/Ripe/x.webp"
    assert (frame, width, quality) == ("ANNOTATED", 400, 60)


def test_a_failed_thumbnail_never_fails_the_capture(settings, storage):
    from palmgrade.services.capture_writer import CaptureWriter

    def boom(path, frame, *, max_width, quality):
        raise OSError("disk penuh")
    storage.write_thumbnail = boom
    assert _pair(CaptureWriter(settings, storage)).endswith("/bbox/Ripe/x.webp")
