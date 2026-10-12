"""Training photos leave the mill photo first, manifest second, and survive outages."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging

from botocore.exceptions import ClientError, EndpointConnectionError

from palmgrade.integrations.erp.outbox_store import GAGAL_KONSOL, GAGAL_TAK_TERJANGKAU, GAGAL_TUJUAN
from palmgrade.integrations.upload.training_outbox_store import TrainingOutboxStore
from palmgrade.workers import training_upload_worker as mod
from palmgrade.workers.training_upload_worker import TrainingUploadWorker

MANIFEST = {
    "schema": "autograde-training-sample/v1", "event_id": "e-1", "captured_at": "2026-10-05T03:12:44+00:00",
    "capture_type": "auto", "folder": {"day": "2026-10-05", "truck": "T"},
    "source": {"company": None, "machine_id": "M1", "line_code": "line-1", "autograde_version": None, "model_file": None},
    "visit": {"truck_id": None, "assignment_id": None, "plate": None}, "prediction": None,
    "priority": {"reasons": [], "rule_version": 1},
}


class FakeUploader:
    def __init__(self, fail_after: int | None = None, exc: Exception | None = None) -> None:
        self.puts: list[tuple[str, str, bytes]] = []
        self.fail_after = fail_after
        self.exc = exc or EndpointConnectionError(endpoint_url="https://r2")

    def put_bytes(self, body, r2_key, *, content_type):
        if self.fail_after is not None and len(self.puts) >= self.fail_after:
            raise self.exc
        self.puts.append((r2_key, content_type, body))


def _queue(tmp_path, store, event_id="e-1", body=b"RIFFwebp", manifest=None, name=None):
    photo = tmp_path / (name or f"{event_id}.webp")
    if body is not None:
        photo.write_bytes(body)
    store.enqueue(event_id, "line-1", str(photo), manifest or {**MANIFEST, "event_id": event_id})
    return photo


def _status(store, event_id):
    return store._db.execute("SELECT status FROM training_outbox WHERE event_id=?", (event_id,)).fetchone()[0]


def test_photo_then_manifest_with_checksum(tmp_path):
    store = TrainingOutboxStore(tmp_path / "o.db")
    _queue(tmp_path, store)
    up = FakeUploader()
    assert asyncio.run(TrainingUploadWorker(store, up).drain()) == 1
    (k1, t1, b1), (k2, t2, b2) = up.puts
    assert (k1, t1, b1) == ("v1/M1/2026-10-05/e-1.webp", "image/webp", b"RIFFwebp")
    assert (k2, t2) == ("v1/M1/2026-10-05/e-1.json", "application/json")
    sent = json.loads(b2)
    assert sent["image"] == {"key": k1, "sha256": hashlib.sha256(b"RIFFwebp").hexdigest(), "bytes": 8,
                             "content_type": "image/webp"}
    assert store.pending_count() == 0
    assert store.last_sent_at() is not None


def test_network_failure_stops_the_pass_and_keeps_the_rows(tmp_path):
    store = TrainingOutboxStore(tmp_path / "o.db")
    for e in ("e-1", "e-2", "e-3"):
        _queue(tmp_path, store, e)
    up = FakeUploader(fail_after=0)
    assert asyncio.run(TrainingUploadWorker(store, up).drain()) == 0
    assert store.failed_count() == 1
    assert store.pending_count() == 2
    assert store.failed_rows()[0]["error_kind"] == GAGAL_TAK_TERJANGKAU


def test_any_upload_failure_stops_the_pass(tmp_path):
    # D5: a bucket typo (404) fails every row the same way; one row pays, not all of them.
    store = TrainingOutboxStore(tmp_path / "o.db")
    for e in ("e-1", "e-2", "e-3"):
        _queue(tmp_path, store, e)
    nosuchbucket = ClientError(
        {"Error": {"Code": "NoSuchBucket"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "PutObject"
    )
    up = FakeUploader(fail_after=0, exc=nosuchbucket)
    assert asyncio.run(TrainingUploadWorker(store, up).drain()) == 0
    assert store.failed_count() == 1
    assert store.pending_count() == 2
    assert store.failed_rows()[0]["error_kind"] == GAGAL_TUJUAN


def test_an_outage_logs_one_warning_per_tick(tmp_path, caplog):
    store = TrainingOutboxStore(tmp_path / "o.db")
    for e in ("e-1", "e-2", "e-3"):
        _queue(tmp_path, store, e)
    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        asyncio.run(TrainingUploadWorker(store, FakeUploader(fail_after=0)).drain())
    assert len([r for r in caplog.records if r.name == mod.__name__]) == 1
    assert "e-1" in caplog.records[0].getMessage()


def test_manifest_failure_leaves_the_row_for_a_full_retry(tmp_path):
    clock = [1000.0]
    store = TrainingOutboxStore(tmp_path / "o.db", clock=lambda: clock[0])
    _queue(tmp_path, store)
    up = FakeUploader(fail_after=1)  # photo lands, manifest does not
    w = TrainingUploadWorker(store, up, clock=lambda: clock[0])
    assert asyncio.run(w.drain()) == 0
    assert store.failed_count() == 1
    clock[0] += 30
    up.fail_after = None
    assert asyncio.run(w.drain()) == 1
    # The retry sends both again: photo first, then the manifest nexio waits for.
    assert [k for k, _, _ in up.puts] == [
        "v1/M1/2026-10-05/e-1.webp", "v1/M1/2026-10-05/e-1.webp", "v1/M1/2026-10-05/e-1.json"
    ]


def test_missing_photo_is_gone_and_the_next_row_still_goes(tmp_path):
    store = TrainingOutboxStore(tmp_path / "o.db")
    _queue(tmp_path, store, "e-1", body=None)
    _queue(tmp_path, store, "e-2")
    up = FakeUploader()
    assert asyncio.run(TrainingUploadWorker(store, up).drain()) == 1
    assert [k for k, _, _ in up.puts] == ["v1/M1/2026-10-05/e-2.webp", "v1/M1/2026-10-05/e-2.json"]
    assert store.pending_count() == 0
    assert store.failed_count() == 0
    assert _status(store, "e-1") == "gone"


def test_empty_photo_is_gone(tmp_path):
    store = TrainingOutboxStore(tmp_path / "o.db")
    _queue(tmp_path, store, body=b"")
    up = FakeUploader()
    asyncio.run(TrainingUploadWorker(store, up).drain())
    assert up.puts == []
    assert store.pending_count() == 0
    assert _status(store, "e-1") == "gone"


def test_leftover_tmp_photo_is_gone_and_the_next_row_still_goes(tmp_path):
    store = TrainingOutboxStore(tmp_path / "o.db")
    _queue(tmp_path, store, "e-1", name=".e-1.webp.ab12.tmp")
    _queue(tmp_path, store, "e-2")
    up = FakeUploader()
    assert asyncio.run(TrainingUploadWorker(store, up).drain()) == 1
    assert _status(store, "e-1") == "gone"
    assert [k for k, _, _ in up.puts][-1] == "v1/M1/2026-10-05/e-2.json"


def test_unreadable_photo_is_held_and_the_next_row_still_goes(tmp_path):
    # D5: a read error on one row (here a directory where the photo should be) marks
    # that row only; it may read next time, so it is not `gone`.
    store = TrainingOutboxStore(tmp_path / "o.db")
    (tmp_path / "e-1.webp").mkdir()
    _queue(tmp_path, store, "e-1", body=None)
    _queue(tmp_path, store, "e-2")
    up = FakeUploader()
    assert asyncio.run(TrainingUploadWorker(store, up).drain()) == 1
    assert _status(store, "e-1") == "error"
    assert store.failed_rows()[0]["error_kind"] == GAGAL_KONSOL
    assert _status(store, "e-2") == "sent"


def test_a_manifest_that_cannot_be_built_holds_that_row_only(tmp_path):
    # Preflight 5.1: one malformed manifest must not stall the queue behind it.
    store = TrainingOutboxStore(tmp_path / "o.db")
    broken = {k: v for k, v in MANIFEST.items() if k != "captured_at"}
    _queue(tmp_path, store, "e-1", manifest=broken)
    _queue(tmp_path, store, "e-2")
    up = FakeUploader()
    assert asyncio.run(TrainingUploadWorker(store, up).drain()) == 1
    assert _status(store, "e-1") == "error"
    assert store.failed_rows()[0]["error_kind"] == GAGAL_KONSOL
    assert [k for k, _, _ in up.puts] == ["v1/M1/2026-10-05/e-2.webp", "v1/M1/2026-10-05/e-2.json"]


def test_drain_keeps_going_until_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_BATCH", 2)
    store = TrainingOutboxStore(tmp_path / "o.db")
    for i in range(5):
        _queue(tmp_path, store, f"e-{i}")
    up = FakeUploader()
    assert asyncio.run(TrainingUploadWorker(store, up).drain()) == 5
    assert store.pending_count() == 0


def test_drain_does_not_stop_on_a_short_batch_of_set_aside_rows(tmp_path, monkeypatch):
    # A full batch where one row is held still lets the rows behind it go in the same tick.
    monkeypatch.setattr(mod, "_BATCH", 2)
    store = TrainingOutboxStore(tmp_path / "o.db")
    _queue(tmp_path, store, "e-0", body=None)
    for i in range(1, 6):
        _queue(tmp_path, store, f"e-{i}")
    assert asyncio.run(TrainingUploadWorker(store, FakeUploader()).drain()) == 5
    assert store.pending_count() == 0


def test_drain_prunes_old_done_rows(tmp_path):
    clock = [1000.0]
    store = TrainingOutboxStore(tmp_path / "o.db", clock=lambda: clock[0])
    _queue(tmp_path, store)
    w = TrainingUploadWorker(store, FakeUploader(), clock=lambda: clock[0])
    asyncio.run(w.drain())
    clock[0] += 8 * 86400
    asyncio.run(w.drain())
    assert store._db.execute("SELECT COUNT(*) FROM training_outbox").fetchone()[0] == 0
