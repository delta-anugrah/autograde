"""The training outbox: one row per bunch, never sent twice, never lost to a restart."""
from __future__ import annotations

import sqlite3

from palmgrade.integrations.erp.outbox_store import GAGAL_KONSOL, GAGAL_TAK_TERJANGKAU
from palmgrade.integrations.upload.training_outbox_store import KEEP_DONE_S, TrainingOutboxStore


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _store(tmp_path, clock=None):
    return TrainingOutboxStore(tmp_path / "training_outbox.db", clock=clock or Clock())


def test_enqueue_is_idempotent_and_never_resets_a_sent_row(tmp_path):
    s = _store(tmp_path)
    assert s.enqueue("e-1", "line-1", "/p/1.webp", {"event_id": "e-1"}) is True
    assert s.enqueue("e-1", "line-1", "/p/1.webp", {"event_id": "e-1"}) is False
    s.mark_sent("e-1")
    assert s.enqueue("e-1", "line-1", "/p/1.webp", {"event_id": "e-1"}) is False
    assert s.due(10) == []


def test_enqueue_twice_gives_exactly_one_row(tmp_path):
    s = _store(tmp_path)
    s.enqueue("e-1", "line-1", "/p/1.webp", {"v": 1})
    s.enqueue("e-1", "line-2", "/p/other.webp", {"v": 2})
    rows = s.due(10)
    assert len(rows) == 1
    assert rows[0].line_code == "line-1" and rows[0].manifest == {"v": 1}


def test_due_is_oldest_first_and_round_trips_the_manifest(tmp_path):
    clock = Clock()
    s = _store(tmp_path, clock)
    s.enqueue("e-2", "line-2", "/p/2.webp", {"event_id": "e-2", "n": [1, 2]})
    clock.t += 1
    s.enqueue("e-1", "line-1", "/p/1.webp", {"event_id": "e-1"})
    rows = s.due(10)
    assert [r.event_id for r in rows] == ["e-2", "e-1"]
    assert rows[0].manifest == {"event_id": "e-2", "n": [1, 2]}
    assert rows[0].line_code == "line-2" and rows[0].photo_path == "/p/2.webp"


def test_error_backs_off_then_comes_due_again(tmp_path):
    clock = Clock()
    s = _store(tmp_path, clock)
    s.enqueue("e-1", "line-1", "/p/1.webp", {})
    s.mark_error("e-1", "boom", jenis=GAGAL_TAK_TERJANGKAU)
    assert s.due(10) == []
    assert s.failed_count() == 1
    clock.t += 30
    assert [r.attempts for r in s.due(10)] == [1]
    s.mark_error("e-1", "boom", jenis=GAGAL_TAK_TERJANGKAU)
    clock.t += 59
    assert s.due(10) == []
    clock.t += 1
    assert len(s.due(10)) == 1


def test_one_bad_row_does_not_block_the_others(tmp_path):
    clock = Clock()
    s = _store(tmp_path, clock)
    s.enqueue("bad", "line-1", "/p/b.webp", {})
    clock.t += 1
    s.enqueue("good", "line-1", "/p/g.webp", {})
    s.mark_error("bad", "unreadable", jenis=GAGAL_TAK_TERJANGKAU)
    assert [r.event_id for r in s.due(10)] == ["good"]


def test_backoff_caps_at_an_hour(tmp_path):
    clock = Clock()
    s = _store(tmp_path, clock)
    s.enqueue("e-1", "line-1", "/p/1.webp", {})
    for _ in range(20):
        s.mark_error("e-1", "x", jenis=GAGAL_TAK_TERJANGKAU)
    clock.t += 3600
    assert len(s.due(10)) == 1


def test_gone_is_terminal_and_not_counted_as_failed(tmp_path):
    s = _store(tmp_path)
    s.enqueue("e-1", "line-1", "/p/1.webp", {})
    s.mark_gone("e-1", "photo missing")
    assert s.due(10) == []
    assert s.failed_count() == 0
    assert s.pending_count() == 0


def test_counts_failed_rows_and_last_sent(tmp_path):
    clock = Clock()
    s = _store(tmp_path, clock)
    for e in ("e-1", "e-2", "e-3"):
        s.enqueue(e, "line-1", f"/p/{e}.webp", {})
    s.mark_error("e-2", "raw text", jenis=GAGAL_TAK_TERJANGKAU)
    clock.t = 2000.0
    s.mark_sent("e-3")
    assert s.pending_count() == 1
    assert s.failed_count() == 1
    assert s.last_sent_at() == 2000.0
    row = s.failed_rows()[0]
    assert row == {
        "kind": "line-1",
        "key": "e-2",
        "last_error": "raw text",
        "error_kind": GAGAL_TAK_TERJANGKAU,
        "attempts": 1,
        "next_attempt_at": row["next_attempt_at"],
    }


def test_last_sent_at_is_none_when_nothing_was_sent(tmp_path):
    assert _store(tmp_path).last_sent_at() is None


def test_prune_drops_done_rows_after_a_week_only(tmp_path):
    clock = Clock()
    s = _store(tmp_path, clock)
    s.enqueue("old", "line-1", "/p/o.webp", {})
    s.mark_sent("old")
    s.enqueue("gone", "line-1", "/p/g.webp", {})
    s.mark_gone("gone", "missing")
    s.enqueue("waiting", "line-1", "/p/w.webp", {})
    clock.t += KEEP_DONE_S + 1
    assert s.prune() == 2
    assert [r.event_id for r in s.due(10)] == ["waiting"]


def test_hapus_semua_counts_rows(tmp_path):
    s = _store(tmp_path)
    s.enqueue("e-1", "line-1", "/p/1.webp", {})
    s.enqueue("e-2", "line-1", "/p/2.webp", {})
    assert s.hapus_semua() == 2
    assert s.pending_count() == 0


def test_durability_pragmas_and_schema_version(tmp_path):
    _store(tmp_path)
    db = sqlite3.connect(tmp_path / "training_outbox.db")
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_a_queued_row_survives_a_restart(tmp_path):
    _store(tmp_path).enqueue("e-1", "line-1", "/p/1.webp", {"a": 1})
    again = _store(tmp_path)
    assert [r.event_id for r in again.due(10)] == ["e-1"]


def test_due_uses_the_index(tmp_path):
    s = _store(tmp_path)
    plan = s._db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM training_outbox WHERE status IN ('pending','error') AND next_attempt_at <= 0"
    ).fetchall()
    assert any("idx_training_outbox_due" in str(tuple(r)) for r in plan)


def test_mark_error_never_resurrects_a_done_row(tmp_path):
    # A late error report (e.g. a pass racing a Danger Zone or a second worker) must not
    # bring a sent photo back into the queue: a sent photo is never sent again.
    s = _store(tmp_path)
    s.enqueue("sent", "line-1", "/p/s.webp", {})
    s.mark_sent("sent")
    s.enqueue("gone", "line-1", "/p/g.webp", {})
    s.mark_gone("gone", "missing")
    s.mark_error("sent", "late", jenis=GAGAL_TAK_TERJANGKAU)
    s.mark_error("gone", "late", jenis=GAGAL_TAK_TERJANGKAU)
    status = dict(s._db.execute("SELECT event_id, status FROM training_outbox").fetchall())
    assert status == {"sent": "sent", "gone": "gone"}
    assert s.failed_count() == 0
    assert s.last_sent_at() is not None


def test_due_sets_aside_a_row_whose_manifest_cannot_be_read(tmp_path):
    clock = Clock()
    s = _store(tmp_path, clock)
    s.enqueue("bad", "line-1", "/p/b.webp", {"event_id": "bad"})
    s.enqueue("odd", "line-1", "/p/o.webp", {"event_id": "odd"})
    clock.t += 1
    s.enqueue("good", "line-1", "/p/g.webp", {"event_id": "good"})
    with s._db:
        s._db.execute("UPDATE training_outbox SET manifest='{not json' WHERE event_id='bad'")
        s._db.execute("UPDATE training_outbox SET manifest='[1, 2]' WHERE event_id='odd'")
    assert [r.event_id for r in s.due(10)] == ["good"]
    rows = {r["key"]: r for r in s.failed_rows()}
    assert set(rows) == {"bad", "odd"}
    assert rows["bad"]["last_error"] == "manifest unreadable"
    assert rows["bad"]["error_kind"] == GAGAL_KONSOL
    assert rows["bad"]["attempts"] == 1
    assert rows["bad"]["next_attempt_at"] == clock.t + 3600
    clock.t += 3599
    assert [r.event_id for r in s.due(10)] == ["good"]
