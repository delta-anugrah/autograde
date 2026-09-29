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
    _add(m)
    _add(m)  # scan 2x → tetap 1 row
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


def test_get_recoverable_poisoned_filters_in_sql(m):
    """Only poisoned rows without an image, or poisoned with the given photo prefix."""
    keys = [f"results/2026-07-10/{c}_auto_ripeness.json" for c in "abcde"]
    _add(m, key=keys[0], event_id="e0")                                  # photo prefix
    _add(m, key=keys[1], event_id="e1")                                  # other poison
    _add(m, key=keys[2], event_id="e2", image_path=None, r2_key=None)    # no image
    _add(m, key=keys[3], event_id="e3")                                  # pending
    _add(m, key=keys[4], event_id="e4")                                  # prefix is a LIKE wildcard trap
    ids = {i["item_key"]: i["id"] for i in m.get_uploadable(limit=10)}
    m.mark_poisoned(ids[keys[0]], "foto bukti kosong (0 byte)")
    m.mark_poisoned(ids[keys[1]], "HTTP 400: bad")
    m.mark_poisoned(ids[keys[2]], "JSON kosong")
    m.mark_poisoned(ids[keys[4]], "fotoXbukti kosong")

    # Prefix taken literally: `_` is not a wildcard, so "fotoXbukti" does not match.
    assert [g["item_key"] for g in m.get_recoverable_poisoned("foto_bukti")] == [keys[2]]
    got = m.get_recoverable_poisoned("foto bukti ")
    assert [(g["item_key"], g["last_error"]) for g in got] == [
        (keys[0], "foto bukti kosong (0 byte)"),
        (keys[2], "JSON kosong"),
    ]
    assert got[0]["image_path"] == "captures/results/2026-07-10/a_auto.webp"
    assert got[1]["image_path"] is None


def test_set_image_fills_a_pending_row_only(m):
    _add(m, image_path=None, r2_key=None)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    m.set_image(item_id, image_path="captures/results/d/x_auto.webp", r2_key="M1/results/d/x_auto.webp")
    got = m.get_uploadable(limit=10)[0]
    assert (got["status"], got["image_path"], got["r2_key"]) == (
        "pending", "captures/results/d/x_auto.webp", "M1/results/d/x_auto.webp",
    )

    m.mark_done(item_id)
    m.set_image(item_id, image_path="lain.webp", r2_key="lain")
    row = m._db.execute("SELECT image_path FROM upload_items WHERE id=?", (item_id,)).fetchone()
    assert row["image_path"] == "captures/results/d/x_auto.webp"


def test_revive_returns_poisoned_item_to_a_fresh_pending(m):
    _add(m, image_path=None, r2_key=None)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    m.requeue(item_id, "PUT R2 gagal")
    m.mark_poisoned(item_id, "JSON kosong")

    m.revive(item_id, image_path="captures/results/d/x_auto.webp", r2_key="M1/results/d/x_auto.webp")

    got = m.get_uploadable(limit=10)
    assert [(g["id"], g["status"], g["image_path"], g["r2_key"], g["retry_count"]) for g in got] == [
        (item_id, "pending", "captures/results/d/x_auto.webp", "M1/results/d/x_auto.webp", 0),
    ]
    row = m._db.execute("SELECT last_error FROM upload_items WHERE id=?", (item_id,)).fetchone()
    assert row["last_error"] is None
    assert m.get_recoverable_poisoned("foto bukti ") == []


def test_revive_leaves_non_poisoned_items_alone(m):
    _add(m)
    item_id = m.get_uploadable(limit=10)[0]["id"]
    m.mark_done(item_id)
    m.revive(item_id, image_path=None, r2_key=None)
    assert m.counts()["done"] == 1


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
