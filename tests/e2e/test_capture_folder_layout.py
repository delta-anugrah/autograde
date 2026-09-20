"""End-to-end: a graded bunch lands on a real disk, and the uploader still finds it.

The unit tests stub storage, so they prove the paths are *computed* correctly.
What they cannot prove is the part that actually broke things before: real WebP
files written through cv2, at a nesting depth `BatchUploadWorker._scan()` has to
keep matching, and retention then removing every byte it put there.

That last chain is the expensive one to get wrong. A sidecar one level too deep
makes the cloud upload find nothing — no exception, no log, just a queue that
never drains. A clean copy retention cannot see fills the disk until
`write_image` raises and grading stops saving.

Needs cv2 and numpy (it writes real images), so it lives in e2e, not the
CI-light unit suite.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.integrations.upload.upload_manifest import UploadManifest  # noqa: E402
from palmgrade.repositories.capture_repository import CaptureRepository  # noqa: E402
from palmgrade.workers.batch_upload_worker import BatchUploadWorker  # noqa: E402

JAKARTA = ZoneInfo("Asia/Jakarta")
MACHINE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(
        Settings(),
        repo_root=tmp_path,
        machine_id=MACHINE_ID,
        factory_tz="Asia/Jakarta",
        r2_bucket="bucket",
        upload_disk_min_free_gb=0,
    )


@pytest.fixture
def frame():
    """Wider than `_THUMB_WIDTH` (400) on purpose: a 32px frame would skip the
    resize branch entirely, and the thumbnail would be proved only by its path."""
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, (768, 1024, 3), dtype=np.uint8)


def _save_one(settings, frame, *, assigned_at: str | None = None) -> dict:
    """One manual reject through the real repository and real file storage."""
    return CaptureRepository(settings, LocalFileStorage()).save_manual_reject(
        frame=frame,
        truck_id="truck-1",
        assignment_id="a3f9c201-dead-beef",
        plate="B 1234 XY",
        assigned_at=assigned_at
        or datetime.datetime(2026, 9, 8, 9, 14, 32, tzinfo=JAKARTA).isoformat(),
    )


def _images(settings) -> list[Path]:
    return sorted(settings.results_dir.rglob("*.webp"))


def _day_folder(settings) -> Path:
    """The day folder as the code names it: UTC, from the capture's own instant.

    Deriving it here rather than hard-coding a date keeps this passing on any
    day it runs — and documents that only the *truck* folder follows the mill
    clock, while the day folder stays UTC (`capture_layout`, rule 2).
    """
    (day,) = [p for p in settings.results_dir.iterdir() if p.is_dir()]
    assert day.name == datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    return day


def test_a_capture_writes_three_real_images_under_its_truck(settings, frame):
    result = _save_one(settings, frame)

    images = _images(settings)
    assert len(images) == 3
    for image in images:
        assert image.stat().st_size > 0, "cv2 wrote an empty file"

    # `unknown/`: capture manual tidak pernah lewat model, jadi kelasnya memang
    # tidak ada. Meminjam kelas yang tak pernah diberikan akan mencemari folder
    # latih dengan gambar berlabel karangan.
    truck = _day_folder(settings) / "091432_B1234XY_a3f9c201"
    assert (truck / "bbox" / "unknown").is_dir()
    assert (truck / "clean" / "unknown").is_dir()
    assert (truck / "thumb" / "unknown").is_dir()
    assert "/091432_B1234XY_a3f9c201/bbox/unknown/" in result["image_url"]


def test_the_thumbnail_is_really_smaller_than_the_evidence(settings, frame):
    """The whole point of the third copy: a 500-bunch page loads previews, not
    full frames. Only a real cv2 write can show the resize actually happened —
    the unit suite stubs storage, so it can only prove the path.
    """
    _save_one(settings, frame)
    truck = _day_folder(settings) / "091432_B1234XY_a3f9c201"
    (annotated,) = (truck / "bbox" / "unknown").glob("*.webp")
    (thumb,) = (truck / "thumb" / "unknown").glob("*.webp")

    width, height = cv2.imread(str(thumb)).shape[1], cv2.imread(str(thumb)).shape[0]
    assert width == 400, "thumbnail was not resized to _THUMB_WIDTH"
    assert height == 300, "aspect ratio of a 1024x768 frame must be kept"
    assert thumb.stat().st_size < annotated.stat().st_size


def test_the_sidecar_sits_where_the_uploader_globs_for_it(settings, frame):
    _save_one(settings, frame)

    # The literal pattern from BatchUploadWorker._scan().
    found = list(settings.results_dir.glob("*/*_ripeness.json"))
    assert len(found) == 1, "the cloud upload finds work with exactly this glob"


def test_the_uploader_picks_up_the_capture_and_resolves_its_image(settings, frame):
    """`_scan()` → manifest → the local file the R2 PUT would read."""
    _save_one(settings, frame)
    worker = BatchUploadWorker(
        settings=settings,
        manifest=UploadManifest(settings.state_dir / "upload_manifest.db"),
        uploader=None,
    )

    worker._scan()

    items = worker.manifest.get_uploadable(limit=10)
    assert len(items) == 1
    item = items[0]
    local = settings.artifacts_dir / item["image_path"].lstrip("/").removeprefix("captures/")
    assert local.exists(), "the path recorded for upload must resolve on disk"
    assert "/bbox/" in item["r2_key"], "R2 receives the annotated copy"


def test_retention_removes_every_byte_the_capture_wrote(settings, frame):
    _save_one(settings, frame)
    worker = BatchUploadWorker(
        settings=settings,
        manifest=UploadManifest(settings.state_dir / "upload_manifest.db"),
        uploader=None,
    )
    worker._scan()
    worker.manifest.mark_done(worker.manifest.get_uploadable(limit=10)[0]["id"])

    import time

    for item in worker.manifest.get_expired_done(time.time() + 86_400):
        worker._delete_item_files(item)

    assert _images(settings) == [], "a clean copy nothing deletes fills the disk"
    assert list(settings.results_dir.rglob("*.json")) == []


def test_the_folder_hour_is_the_mill_clock(settings, frame):
    """16:00 WIB is 09:00 UTC; the folder must read 16, or nobody finds it."""
    _save_one(
        settings,
        frame,
        assigned_at=datetime.datetime(2026, 9, 8, 16, 0, 0, tzinfo=JAKARTA).isoformat(),
    )

    assert any("/160000_B1234XY_" in str(p) for p in _images(settings))


def test_a_second_truck_gets_its_own_folder(settings, frame):
    """The whole point: one day folder, one sub-folder per visit."""
    storage = LocalFileStorage()
    repo = CaptureRepository(settings, storage)
    for assignment, plate, hour in (("aaaa1111", "B1111AA", 8), ("bbbb2222", "B2222BB", 11)):
        repo.save_manual_reject(
            frame=frame,
            truck_id=f"truck-{assignment}",
            assignment_id=assignment,
            plate=plate,
            assigned_at=datetime.datetime(2026, 9, 8, hour, 0, 0, tzinfo=JAKARTA).isoformat(),
        )

    trucks = sorted(p.name for p in _day_folder(settings).iterdir() if p.is_dir())
    assert trucks == ["080000_B1111AA_aaaa1111", "110000_B2222BB_bbbb2222"]
    # Sorted listing is chronological — the only index the factory PC has.
    assert trucks == sorted(trucks)


def test_the_sidecar_survives_a_round_trip_through_disk(settings, frame):
    """It is written now and read hours later by a different process."""
    _save_one(settings, frame)

    (sidecar,) = settings.results_dir.glob("*/*_ripeness.json")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))

    assert meta["ripeness_status"] == "rej"
    assert meta["capture_type"] == "manual"
    assert "/bbox/" in meta["image_url"]
