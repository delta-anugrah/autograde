"""Unit tests for outbox dead-letter visibility + requeue (M1).

Events that fail delivery _MAX_RETRIES times become status='failed' permanently
and used to be invisible (pending_count only counts 'pending') → silent data
loss. These tests lock the new failed_count() and requeue_failed() so a stuck
event can be seen in /health/detail and re-sent. Uses tmp_path SQLite.
"""
from __future__ import annotations

from palmgrade.integrations.outbox.outbox_store import _MAX_RETRIES, OutboxStore


def _store(tmp_path):
    return OutboxStore(db_path=tmp_path / "outbox.db")


def _dead_letter(store, event_id="e1"):
    store.add_event(event_id, "m1", {"event_id": event_id})
    row_id = [r for r in store.get_pending() if r["event_id"] == event_id][0]["id"]
    for _ in range(_MAX_RETRIES):
        store.mark_failed_attempt(row_id, "boom")
    return row_id


def test_failed_count_zero_initially(tmp_path):
    store = _store(tmp_path)
    store.add_event("e1", "m1", {"event_id": "e1"})
    assert store.failed_count() == 0


def test_failed_count_counts_dead_letters(tmp_path):
    store = _store(tmp_path)
    _dead_letter(store, "e1")
    assert store.failed_count() == 1
    assert store.pending_count() == 0  # not double-counted as pending


def test_requeue_failed_moves_back_to_pending(tmp_path):
    store = _store(tmp_path)
    _dead_letter(store, "e1")

    moved = store.requeue_failed()

    assert moved == 1
    assert store.failed_count() == 0
    assert store.pending_count() == 1
    # Requeued event is immediately eligible (retry counter + backoff reset).
    pending = store.get_pending()
    assert len(pending) == 1
    assert pending[0]["retry_count"] == 0


def test_requeue_failed_noop_when_none(tmp_path):
    store = _store(tmp_path)
    store.add_event("e1", "m1", {"event_id": "e1"})  # still pending, not failed
    assert store.requeue_failed() == 0
    assert store.pending_count() == 1


def test_requeue_multiple_dead_letters(tmp_path):
    store = _store(tmp_path)
    _dead_letter(store, "e1")
    _dead_letter(store, "e2")
    assert store.failed_count() == 2
    assert store.requeue_failed() == 2
    assert store.pending_count() == 2
