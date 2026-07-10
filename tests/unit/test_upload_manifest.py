"""Unit tests manifest batch-upload (spec 2026-07-10 §3.1, §7.1-7.3).

Manifest = jaminan durability alur batch: pending → image_uploaded → done
(+ poisoned). Beda kontrak dgn outbox lama: TANPA retry cap, TANPA TTL.
SQLite asli di tmp_path (bukan mock) — durability-nya justru yang di-test.
"""
from __future__ import annotations

import time

import pytest

from palmgrade.integrations.upload.upload_manifest import (
    _BACKOFF_BASE,
    _BACKOFF_MAX,
    UploadManifest,
)


@pytest.fixture
def m(tmp_path):
    return UploadManifest(db_path=tmp_path / "upload_manifest.db")


def _add(m, key="results/2026-07-10/a_auto_ripeness.json", **over):
    kw = dict(event_id="e1", image_path="captures/results/2026-07-10/a_auto.webp",
              r2_key="M1/results/2026-07-10/a_auto.webp")
    kw.update(over)
    m.upsert_item(key, **kw)


def test_scan_idempotent(m):
    _add(m); _add(m)  # scan 2x → tetap 1 row
    assert m.counts()["pending"] == 1
    assert m.has_item("results/2026-07-10/a_auto_ripeness.json")


def test_state_transitions(m):
    _add(m)
    item = m.get_uploadable(limit=10)[0]
    m.mark_image_uploaded(item["id"])
    assert m.get_uploadable(limit=10)[0]["status"] == "image_uploaded"
    m.mark_done(item["id"])
    assert m.get_uploadable(limit=10) == []
    assert m.counts()["done"] == 1


def test_done_never_reprocessed(m):
    _add(m)
    m.mark_done(m.get_uploadable(limit=10)[0]["id"])
    _add(m)  # re-scan file yang sama
    assert m.counts() == {"pending": 0, "image_uploaded": 0, "done": 1, "poisoned": 0}


def test_requeue_backoff_no_cap(m):
    # "tahan durasi outage apa pun": gagal 100x → TETAP eligible nanti, tak ada dead-letter
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    before = time.time()
    for _ in range(100):
        m.requeue(item_id, "ConnectionError")
    row = m._db.execute("SELECT status, retry_count, next_retry_at FROM upload_items WHERE id=?",
                        (item_id,)).fetchone()
    assert row["status"] == "pending"           # bukan 'failed'
    assert row["retry_count"] == 100
    assert row["next_retry_at"] - before <= _BACKOFF_MAX + 1


def test_requeue_first_backoff_is_base(m):
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    before = time.time()
    m.requeue(item_id, "timeout")
    row = m._db.execute("SELECT next_retry_at FROM upload_items WHERE id=?", (item_id,)).fetchone()
    assert _BACKOFF_BASE - 1 <= row["next_retry_at"] - before <= _BACKOFF_BASE + 2
    assert m.get_uploadable(limit=10) == []     # backed off → tidak eligible sekarang


def test_requeue_preserves_state(m):
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    m.mark_image_uploaded(item_id)
    m.requeue(item_id, "HTTP 503")
    row = m._db.execute("SELECT status FROM upload_items WHERE id=?", (item_id,)).fetchone()
    assert row["status"] == "image_uploaded"    # resume dari teks, gambar tak diulang


def test_poisoned_excluded(m):
    _add(m)
    _add(m, key="results/2026-07-10/b_auto_ripeness.json", event_id="e2")
    items = m.get_uploadable(limit=10)
    m.mark_poisoned(items[0]["id"], "json korup")
    left = m.get_uploadable(limit=10)
    assert len(left) == 1 and left[0]["id"] == items[1]["id"]


def test_oldest_first_and_limit(m):
    for i in range(5):
        _add(m, key=f"results/d/{i}_auto_ripeness.json", event_id=f"e{i}")
        time.sleep(0.01)
    got = m.get_uploadable(limit=3)
    assert [g["item_key"] for g in got] == [f"results/d/{i}_auto_ripeness.json" for i in range(3)]


def test_retention_query(m):
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    m.mark_done(item_id)
    assert m.get_expired_done(cutoff=time.time() + 10)[0]["id"] == item_id
    assert m.get_expired_done(cutoff=time.time() - 10) == []
    m.delete_item(item_id)
    assert m.counts()["done"] == 0


def test_wal_survives_reopen(tmp_path):
    db = tmp_path / "upload_manifest.db"
    m1 = UploadManifest(db_path=db)
    m1.upsert_item("k1", event_id="e1", image_path=None, r2_key=None)
    m1.mark_image_uploaded(m1.get_uploadable(limit=1)[0]["id"])
    m2 = UploadManifest(db_path=db)  # "restart"
    assert m2.get_uploadable(limit=1)[0]["status"] == "image_uploaded"
    assert m2._db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
