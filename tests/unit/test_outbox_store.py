"""Unit tests for the durable outbox store (B1).

The outbox is the crash-safe delivery guarantee between vision and palmgrade-api:
detection events are persisted here, then OutboxRetryWorker ships them with
exponential backoff. These tests lock durability, idempotency (uuid5 dedupe), and
backoff/dead-letter behavior. Uses a throwaway SQLite DB in tmp_path.
"""
from __future__ import annotations

import time

import pytest

from palmgrade.integrations.outbox.outbox_store import (
    _BACKOFF_BASE,
    _BACKOFF_MAX,
    _MAX_RETRIES,
    OutboxStore,
)


@pytest.fixture
def store(tmp_path):
    return OutboxStore(db_path=tmp_path / "outbox.db")


def _payload(**over):
    base = {"event_id": "e1", "prediction": "Acc", "ripeness_status": "ACC"}
    base.update(over)
    return base


def test_add_then_pending_returns_event(store):
    store.add_event("e1", "m1", _payload())
    pending = store.get_pending()

    assert len(pending) == 1
    assert pending[0]["event_id"] == "e1"
    assert store.pending_count() == 1


def test_duplicate_event_id_is_ignored(store):
    # uuid5 makes event_id deterministic: reprocessing the same frame after a
    # crash must NOT create a second outbox row.
    store.add_event("dup", "m1", _payload(event_id="dup"))
    store.add_event("dup", "m1", _payload(event_id="dup"))

    assert store.pending_count() == 1


def test_mark_delivered_removes_row(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    store.mark_delivered(row_id)

    assert store.pending_count() == 0
    assert store.get_pending() == []


def test_failed_attempt_backs_off_and_stays_pending(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    store.mark_failed_attempt(row_id, "HTTP 500")

    # Backed off into the future → not immediately returned by get_pending.
    assert store.get_pending() == []
    # But still pending (retryable), not delivered/dead.
    assert store.pending_count() == 1


def test_backoff_is_exponential_capped(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    before = time.time()
    store.mark_failed_attempt(row_id, "err")  # retry 1 → base delay
    row = store._db.execute(
        "SELECT retry_count, next_retry_at FROM outbox_events WHERE id=?", (row_id,)
    ).fetchone()
    delay = row["next_retry_at"] - before
    assert row["retry_count"] == 1
    assert _BACKOFF_BASE - 1 <= delay <= _BACKOFF_BASE + 2  # ~5s


def test_exceeding_max_retries_marks_failed(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    for _ in range(_MAX_RETRIES):
        store.mark_failed_attempt(row_id, "boom")

    row = store._db.execute(
        "SELECT retry_count, status FROM outbox_events WHERE id=?", (row_id,)
    ).fetchone()
    assert row["retry_count"] == _MAX_RETRIES
    assert row["status"] == "failed"
    # Dead-lettered rows are no longer counted as pending.
    assert store.pending_count() == 0


def test_backoff_never_exceeds_max(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    before = time.time()
    for _ in range(_MAX_RETRIES - 1):
        before = time.time()
        store.mark_failed_attempt(row_id, "err")
    row = store._db.execute(
        "SELECT next_retry_at FROM outbox_events WHERE id=?", (row_id,)
    ).fetchone()
    assert row["next_retry_at"] - before <= _BACKOFF_MAX + 1


def test_wal_mode_enabled(store):
    mode = store._db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
