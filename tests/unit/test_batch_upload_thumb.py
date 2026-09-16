"""The thumbnail rides up with the annotated image, and is deleted with it.

It has no manifest row of its own (same reasoning as the clean copy): one state
machine per bunch, the siblings follow the annotated file.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.workers.batch_upload_worker import BatchUploadWorker

MACHINE_ID = "11111111-1111-1111-1111-111111111111"
DAY = "2026-09-08"
TRUCK = "091432_B1234XY_a3f9c201"
STAMP = f"{DAY}_021432_781225"


class FakeUploader:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def put(self, local_path, r2_key, *, content_type="image/webp") -> None:
        self.keys.append(r2_key)


@pytest.fixture
def settings(tmp_path) -> Settings:
    # UPLOAD_API_URL deliberately empty: no text receiver (see A4).
    return replace(Settings(), repo_root=tmp_path, machine_id=MACHINE_ID,
                   r2_bucket="bucket", upload_api_url="", upload_disk_min_free_gb=0)


def _capture(settings, *, with_thumb: bool):
    day = settings.results_dir / DAY
    annotated = day / TRUCK / "bbox" / "acc" / f"{STAMP}_auto.webp"
    annotated.parent.mkdir(parents=True)
    annotated.write_bytes(b"bbox")
    if with_thumb:
        thumb = day / TRUCK / "thumb" / "acc" / f"{STAMP}_auto.webp"
        thumb.parent.mkdir(parents=True)
        thumb.write_bytes(b"thumb")
    (day / f"{STAMP}_auto_ripeness.json").write_text(json.dumps({
        "timestamp": "2026-09-08T02:14:32.781225",
        "image_path": f"captures/results/{DAY}/{TRUCK}/bbox/acc/{STAMP}_auto.webp",
        "ripeness_status": "acc", "capture_type": "auto", "assignment_id": "a-1",
    }))


def _run(settings):
    manifest = UploadManifest(db_path=settings.state_dir / "m.db")
    uploader = FakeUploader()
    BatchUploadWorker(settings=settings, manifest=manifest, uploader=uploader).run_batch_once()
    return manifest, uploader


def test_thumb_goes_up_beside_the_annotated_image(settings):
    _capture(settings, with_thumb=True)
    manifest, uploader = _run(settings)
    assert uploader.keys == [
        f"{MACHINE_ID}/results/{DAY}/{TRUCK}/bbox/acc/{STAMP}_auto.webp",
        f"{MACHINE_ID}/results/{DAY}/{TRUCK}/thumb/acc/{STAMP}_auto.webp",
    ]
    assert manifest.counts()["done"] == 1


def test_a_capture_without_a_thumb_still_uploads(settings):
    """Written by an older line, or the thumbnail write failed: never a poison."""
    _capture(settings, with_thumb=False)
    manifest, uploader = _run(settings)
    assert len(uploader.keys) == 1
    assert manifest.counts()["done"] == 1
