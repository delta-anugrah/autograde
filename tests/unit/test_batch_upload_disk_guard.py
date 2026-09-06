"""Penjaga sisa disk pada retensi batch upload.

Retensi berbasis umur bertaruh throughput tidak melebihi perkiraan saat
UPLOAD_RETENTION_DAYS disetel. Kalau taruhan itu kalah, disk penuh dan
`LocalFileStorage.write_image` raise — grading berhenti tersimpan. Penjaga ini
membuang `done` tertua lebih awal supaya itu tidak terjadi.
"""
from __future__ import annotations

import json
import time

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.workers.batch_upload_worker import BatchUploadWorker

GB = 1024**3


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setenv("MACHINE_ID", "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01")
    monkeypatch.setenv("R2_BUCKET", "palmgrade")
    monkeypatch.setenv("UPLOAD_DISK_MIN_FREE_GB", "20")
    monkeypatch.setenv("UPLOAD_RETENTION_DAYS", "180")
    settings = Settings(repo_root=tmp_path)
    manifest = UploadManifest(db_path=tmp_path / "m.db")
    return BatchUploadWorker(settings=settings, manifest=manifest, uploader=None), settings, manifest


def _add_done(settings, manifest, ts: str, uploaded_at: float) -> None:
    """Satu item done lengkap dengan file WebP + JSON-nya di disk."""
    date = ts[:10]
    d = settings.results_dir / date
    d.mkdir(parents=True, exist_ok=True)
    img = f"{ts}_auto.webp"
    (d / img).write_bytes(b"webp")
    key = f"results/{date}/{ts}_auto_ripeness.json"
    (settings.artifacts_dir / key).write_text(json.dumps({"ripeness_status": "acc"}))
    manifest.upsert_item(key, event_id=ts, image_path=f"captures/results/{date}/{img}", r2_key=key)
    item = manifest.get_uploadable(limit=100)[-1]
    manifest.mark_done(item["id"])
    with manifest._lock, manifest._db:
        manifest._db.execute(
            "UPDATE upload_items SET uploaded_at=? WHERE id=?", (uploaded_at, item["id"])
        )


def _fake_free(worker, *readings):
    """Sisa disk berurutan; nilai terakhir dipakai terus setelah habis."""
    seq = list(readings)
    worker._free_bytes = lambda: seq.pop(0) if len(seq) > 1 else seq[0]


def test_deletes_oldest_done_when_disk_below_floor(worker):
    w, settings, manifest = worker
    now = time.time()
    # Ketiganya masih JAUH di dalam 180 hari — retensi umur tidak akan menyentuhnya.
    for i, ts in enumerate(["2026-09-01_080000_000001", "2026-09-02_080000_000002",
                            "2026-09-03_080000_000003"]):
        _add_done(settings, manifest, ts, now - (3 - i) * 86400)

    # Di bawah lantai, lalu lega setelah satu sapuan.
    _fake_free(w, 5 * GB, 25 * GB)
    w._retention()

    assert manifest.counts()["done"] == 0  # satu chunk (200) menyapu ketiganya
    assert list(settings.results_dir.rglob("*.webp")) == []


def test_leaves_everything_alone_when_disk_is_healthy(worker):
    w, settings, manifest = worker
    _add_done(settings, manifest, "2026-09-01_080000_000001", time.time())

    _fake_free(w, 100 * GB)
    w._retention()

    assert manifest.counts()["done"] == 1
    assert len(list(settings.results_dir.rglob("*.webp"))) == 1


def test_stops_instead_of_deleting_items_that_never_reached_the_cloud(worker):
    """Item non-done adalah satu-satunya salinan yang ada — jangan disentuh."""
    w, settings, manifest = worker
    d = settings.results_dir / "2026-09-01"
    d.mkdir(parents=True, exist_ok=True)
    key = "results/2026-09-01/2026-09-01_080000_000001_auto_ripeness.json"
    (settings.artifacts_dir / key).write_text(json.dumps({"ripeness_status": "acc"}))
    manifest.upsert_item(key, event_id="e1", image_path=None, r2_key=None)

    _fake_free(w, 1 * GB)  # tetap di bawah lantai selamanya
    w._retention()  # tidak boleh menggantung di loop

    assert manifest.counts()["pending"] == 1
    assert (settings.artifacts_dir / key).exists()


def test_floor_of_zero_disables_the_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("MACHINE_ID", "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01")
    monkeypatch.setenv("R2_BUCKET", "palmgrade")
    monkeypatch.setenv("UPLOAD_DISK_MIN_FREE_GB", "0")
    settings = Settings(repo_root=tmp_path)
    manifest = UploadManifest(db_path=tmp_path / "m.db")
    w = BatchUploadWorker(settings=settings, manifest=manifest, uploader=None)
    _add_done(settings, manifest, "2026-09-01_080000_000001", time.time())

    called = False

    def _boom():
        nonlocal called
        called = True
        return 1

    w._free_bytes = _boom
    w._retention()

    assert not called  # lantai 0 = disk tidak diintip sama sekali
    assert manifest.counts()["done"] == 1


def test_unreadable_disk_does_not_delete_anything(worker):
    w, settings, manifest = worker
    _add_done(settings, manifest, "2026-09-01_080000_000001", time.time())

    w._free_bytes = lambda: None
    w._retention()

    assert manifest.counts()["done"] == 1


def test_age_based_retention_still_runs(worker):
    """Penjaga disk itu tambahan, bukan pengganti."""
    w, settings, manifest = worker
    _add_done(settings, manifest, "2025-01-01_080000_000001", time.time() - 200 * 86400)
    _add_done(settings, manifest, "2026-09-01_080000_000001", time.time())

    _fake_free(w, 100 * GB)  # disk sehat: hanya jalur umur yang boleh bekerja
    w._retention()

    assert manifest.counts()["done"] == 1
    assert list(settings.results_dir.rglob("*.webp")) == [
        settings.results_dir / "2026-09-01" / "2026-09-01_080000_000001_auto.webp"
    ]
