"""Retention must delete the clean copy too, or the disk fills up silently.

`_delete_item_files` only ever knew about one image per item. A second variant
it does not know about is never deleted by anything: age-based retention skips
it, and so does the disk guard — which then keeps sweeping `done` items that
free only half the space they should, until `write_image` raises and grading
stops saving (Critical Rule #8 and #9).

Nothing here asserts on *where* the clean copy lives; that is
`domain/capture_layout`'s business. Retention only has to find it.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.workers.batch_upload_worker import BatchUploadWorker

MACHINE_ID = "11111111-1111-1111-1111-111111111111"
DAY = "2026-09-08"
TRUCK = "091432_B1234XY_a3f9c201"
STAMP = f"{DAY}_021432_781225"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(
        Settings(),
        repo_root=tmp_path,
        machine_id=MACHINE_ID,
        r2_bucket="bucket",
        upload_retention_days=7,
        upload_disk_min_free_gb=0,  # age-based retention only, no disk sweep
    )


def _write_capture(settings: Settings) -> tuple[Path, Path, Path]:
    """One finished capture on disk: sidecar + annotated + clean."""
    day = settings.results_dir / DAY
    annotated = day / TRUCK / "bbox" / "rej" / f"{STAMP}_auto.webp"
    clean = day / TRUCK / "clean" / "rej" / f"{STAMP}_auto.webp"
    for image in (annotated, clean):
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"webp")

    sidecar = day / f"{STAMP}_auto_ripeness.json"
    sidecar.write_text(
        json.dumps(
            {
                "timestamp": f"{DAY}T02:14:32+00:00",
                "image_path": f"captures/results/{annotated.relative_to(settings.results_dir)}",
                "ripeness_status": "REJ",
                "ripeness_confidence": 0.9,
                "capture_type": "auto",
                "truck_id": "truck-1",
                "bounding_box": {},
            }
        ),
        encoding="utf-8",
    )
    return sidecar, annotated, clean


@pytest.fixture
def worker(settings):
    manifest = UploadManifest(settings.state_dir / "upload_manifest.db")
    return BatchUploadWorker(settings=settings, manifest=manifest, uploader=None)


def _expire_the_only_item(worker, settings) -> dict:
    """Scan, then mark the item done long enough ago to be past the cutoff."""
    worker._scan()
    item = worker.manifest.get_uploadable(limit=10)[0]
    worker.manifest.mark_done(item["id"])
    return item


def test_retention_deletes_both_variants(worker, settings):
    sidecar, annotated, clean = _write_capture(settings)
    _expire_the_only_item(worker, settings)

    # Everything older than "now" is expired when the cutoff is in the future.
    for item in worker.manifest.get_expired_done(time.time() + 86_400):
        worker._delete_item_files(item)

    assert not annotated.exists(), "the evidence copy must go"
    assert not clean.exists(), "the training copy must go with it — nothing else deletes it"
    assert not sidecar.exists()


def test_deleting_is_indifferent_to_a_missing_clean_copy(worker, settings):
    """Captures written before this change have no clean twin. Retention must
    still complete, not raise and leave the rest of the sweep undone.
    """
    sidecar, annotated, clean = _write_capture(settings)
    clean.unlink()
    _expire_the_only_item(worker, settings)

    for item in worker.manifest.get_expired_done(time.time() + 86_400):
        worker._delete_item_files(item)

    assert not annotated.exists()
    assert not sidecar.exists()


def test_a_flat_legacy_image_is_still_deleted(worker, settings):
    """Images written before the per-truck layout sit directly in the day folder.

    They keep arriving in retention for `UPLOAD_RETENTION_DAYS` after the
    upgrade, and an unlink that assumes the new shape would leak every one.
    """
    day = settings.results_dir / DAY
    day.mkdir(parents=True, exist_ok=True)
    legacy_image = day / f"{STAMP}_auto.webp"
    legacy_image.write_bytes(b"webp")
    sidecar = day / f"{STAMP}_auto_ripeness.json"
    sidecar.write_text(
        json.dumps(
            {
                "timestamp": f"{DAY}T02:14:32+00:00",
                "image_path": f"captures/results/{DAY}/{STAMP}_auto.webp",
                "ripeness_status": "REJ",
                "ripeness_confidence": 0.9,
                "capture_type": "auto",
                "truck_id": "truck-1",
                "bounding_box": {},
            }
        ),
        encoding="utf-8",
    )

    _expire_the_only_item(worker, settings)
    for item in worker.manifest.get_expired_done(time.time() + 86_400):
        worker._delete_item_files(item)

    assert not legacy_image.exists()
    assert not sidecar.exists()
