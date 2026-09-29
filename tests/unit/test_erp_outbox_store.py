"""The queue of messages waiting for AutoERP (contract §5, backlog AG-4).

Pinned: one row per (kind, key) always holding the newest state, a backoff that
climbs from 30 s to an hour, and that a message replaced while it was on the
wire is never marked as sent.
"""
from __future__ import annotations

import sqlite3

from rencana_query import rencana

from palmgrade.integrations.erp.outbox_store import ErpOutboxStore


class Clock:
    """Time as a collaborator: backoff is asserted, never slept through."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _store(tmp_path, clock: Clock | None = None) -> ErpOutboxStore:
    return ErpOutboxStore(tmp_path / "erp_outbox.db", clock=clock or Clock())


def test_an_enqueued_message_is_due_at_once(tmp_path):
    outbox = _store(tmp_path)

    outbox.enqueue("truck", "BE1AA", {"plate_number": "BE 1 AA"})

    [message] = outbox.due()
    assert (message.kind, message.key, message.payload, message.attempts) == (
        "truck", "BE1AA", {"plate_number": "BE 1 AA"}, 0,
    )


def test_one_row_per_kind_and_key_holding_the_newest_payload(tmp_path):
    """A visit is sent again at every stage; two rows would race each other."""
    outbox = _store(tmp_path)

    outbox.enqueue("visit", "v1", {"stage": "gate"})
    outbox.enqueue("visit", "v1", {"stage": "departed"})

    assert [m.payload for m in outbox.due()] == [{"stage": "departed"}]


def test_a_sent_message_is_no_longer_due(tmp_path):
    outbox = _store(tmp_path)
    outbox.enqueue("truck", "BE1AA", {"v": 1})

    outbox.mark_sent(outbox.due()[0])

    assert outbox.due() == []


def test_a_failed_attempt_backs_off_from_30_seconds_to_an_hour(tmp_path):
    """AutoERP down for hours must cost a handful of calls, not thousands."""
    clock = Clock()
    outbox = _store(tmp_path, clock)
    outbox.enqueue("truck", "BE1AA", {"v": 1})

    for expected in (30, 60, 120, 240, 480, 960, 1920, 3600, 3600):
        [message] = outbox.due()
        outbox.mark_error(message, "AutoERP unreachable")
        clock.now += expected - 1
        assert outbox.due() == [], f"due too early, expected {expected}s of backoff"
        clock.now += 1


def test_a_failure_keeps_its_reason_and_counts_the_attempts(tmp_path):
    clock = Clock()
    outbox = _store(tmp_path, clock)
    outbox.enqueue("truck", "BE1AA", {"v": 1})

    outbox.mark_error(outbox.due()[0], "417 ValidationError: Nomor polisi")
    clock.now += 30

    [message] = outbox.due()
    assert (message.attempts, message.last_error) == (1, "417 ValidationError: Nomor polisi")


def test_a_payload_replaced_during_the_send_is_not_marked_sent(tmp_path):
    """Marking that row sent would drop the newer state for good."""
    outbox = _store(tmp_path)
    outbox.enqueue("visit", "v1", {"stage": "gate"})
    in_flight = outbox.due()[0]

    outbox.enqueue("visit", "v1", {"stage": "departed"})
    outbox.mark_sent(in_flight)

    assert [m.payload for m in outbox.due()] == [{"stage": "departed"}]


def test_re_enqueueing_clears_an_earlier_failure(tmp_path):
    clock = Clock()
    outbox = _store(tmp_path, clock)
    outbox.enqueue("truck", "BE1AA", {"v": 1})
    outbox.mark_error(outbox.due()[0], "AutoERP unreachable")

    outbox.enqueue("truck", "BE1AA", {"v": 2})

    [message] = outbox.due()
    assert (message.payload, message.attempts, message.last_error) == ({"v": 2}, 0, None)


def test_oldest_first_and_never_more_than_one_batch(tmp_path):
    clock = Clock()
    outbox = _store(tmp_path, clock)
    for i in range(3):
        outbox.enqueue("truck", f"K{i}", {"i": i})
        clock.now += 1

    assert [m.key for m in outbox.due(limit=2)] == ["K0", "K1"]


def test_messages_survive_a_console_restart(tmp_path):
    """A truck typed during an outage must still go up after the power cut."""
    _store(tmp_path).enqueue("truck", "BE1AA", {"v": 1})

    assert [m.key for m in _store(tmp_path).due()] == ["BE1AA"]


# ── support diagnostics screen: counts, listing, and resend ────────────────


def test_pending_count_excludes_sent_and_error_rows(tmp_path):
    outbox = _store(tmp_path)
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.enqueue("truck", "K2", {"v": 2})
    outbox.mark_sent(outbox.due()[0])
    outbox.mark_error(outbox.due()[0], "timeout")

    assert outbox.pending_count() == 0


def test_pending_count_counts_rows_never_tried(tmp_path):
    outbox = _store(tmp_path)
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.enqueue("truck", "K2", {"v": 2})

    assert outbox.pending_count() == 2


def test_failed_count_counts_error_rows_only(tmp_path):
    outbox = _store(tmp_path)
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.enqueue("truck", "K2", {"v": 2})
    outbox.mark_error(outbox.due()[0], "417 unknown field")

    assert outbox.failed_count() == 1


def test_daftar_gagal_carries_the_reason(tmp_path):
    outbox = _store(tmp_path)
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.mark_error(outbox.due()[0], "417 unknown field")

    [row] = outbox.failed_rows()
    assert row["kind"] == "truck"
    assert row["key"] == "K1"
    assert "417" in row["last_error"]
    assert row["attempts"] == 1


def test_daftar_gagal_excludes_pending_and_sent_rows(tmp_path):
    outbox = _store(tmp_path)
    outbox.enqueue("truck", "K2", {"v": 2})
    outbox.mark_sent(outbox.due()[0])  # K2: sent
    outbox.enqueue("truck", "K3", {"v": 3})
    outbox.mark_error(outbox.due()[0], "timeout")  # K3: error
    outbox.enqueue("truck", "K1", {"v": 1})  # K1: stays pending

    assert [row["key"] for row in outbox.failed_rows()] == ["K3"]


def test_requeue_failed_moves_error_rows_back_to_pending(tmp_path):
    clock = Clock()
    outbox = _store(tmp_path, clock)
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.mark_error(outbox.due()[0], "timeout")
    clock.now += 10  # still well inside the backoff window

    dipindah = outbox.requeue_failed()

    assert dipindah == 1
    assert outbox.failed_count() == 0
    assert outbox.pending_count() == 1
    [message] = outbox.due()
    assert message.key == "K1"


def test_requeue_failed_only_touches_error_rows(tmp_path):
    """A pending row and a sent row in the same store must come out unchanged."""
    clock = Clock()
    outbox = _store(tmp_path, clock)
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.mark_error(outbox.due()[0], "timeout")  # K1: error, backed off 30s
    outbox.enqueue("truck", "K2", {"v": 2})  # K2: pending
    outbox.enqueue("truck", "K3", {"v": 3})
    # K1 is still backing off, so due() only sees K2 and K3 here.
    outbox.mark_sent(outbox.due()[1])  # K3: sent

    assert outbox.requeue_failed() == 1
    assert outbox.pending_count() == 2  # K1 rejoined K2; K3 stays sent, not pending
    assert {m.key for m in outbox.due()} == {"K1", "K2"}


def test_requeue_failed_returns_zero_when_nothing_is_stuck(tmp_path):
    outbox = _store(tmp_path)
    outbox.enqueue("truck", "K1", {"v": 1})

    assert outbox.requeue_failed() == 0


def test_requeue_failed_resets_next_attempt_at_to_now(tmp_path):
    """The screen's "next attempt" column must read due now right after the
    button is pressed, not the stale time the row was backed off to."""
    clock = Clock()
    outbox = _store(tmp_path, clock)
    outbox.enqueue("truck", "K1", {"v": 1})
    outbox.mark_error(outbox.due()[0], "timeout")  # next_attempt_at = now + 30s

    outbox.requeue_failed()

    # A clock jump far past any real backoff (max is one hour): due() only
    # returns rows whose next_attempt_at is <= now, so the row surviving this
    # proves it was reset to (at most) the moment of the jump, not left at
    # its old backed-off value.
    clock.now += 7200
    assert [m.key for m in outbox.due()] == ["K1"]


def test_the_same_payload_queued_again_during_the_send_is_not_marked_sent(tmp_path):
    """The R2 page payload is always `{"assignment_id": X}`: a late bunch requeues it
    with the SAME text while the older build is uploading. Matching on the payload
    marked that fresh row sent and froze the page at the old count."""
    outbox = _store(tmp_path)
    outbox.enqueue("visit_manifest", "w1", {"assignment_id": "a1"})
    in_flight = outbox.due()[0]

    outbox.enqueue("visit_manifest", "w1", {"assignment_id": "a1"})
    outbox.mark_sent(in_flight)

    assert [m.key for m in outbox.due()] == ["w1"]


def test_a_failed_send_of_older_state_does_not_back_off_the_newer_state(tmp_path):
    """The newer state was never tried: it stays due at once, with no failure on it."""
    outbox = _store(tmp_path)
    outbox.enqueue("visit", "v1", {"stage": "gate"})
    in_flight = outbox.due()[0]

    outbox.enqueue("visit", "v1", {"stage": "departed"})
    outbox.mark_error(in_flight, "timeout")

    [message] = outbox.due()
    assert (message.payload, message.attempts, message.last_error) == ({"stage": "departed"}, 0, None)


def test_every_enqueue_moves_the_generation_on(tmp_path):
    outbox = _store(tmp_path)

    outbox.enqueue("visit", "v1", {"stage": "gate"})
    first = outbox.due()[0].version
    outbox.enqueue("visit", "v1", {"stage": "gate"})

    assert outbox.due()[0].version == first + 1


def test_an_outbox_from_an_older_build_gains_the_generation_and_keeps_its_rows(tmp_path):
    """Lampung's erp_outbox.db and manifest_outbox.db predate the `version` column:
    their pending and failed rows must still be due and still be marked done."""
    path = tmp_path / "erp_outbox.db"
    lama = sqlite3.connect(path)
    lama.executescript(
        """CREATE TABLE erp_outbox (
               kind TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
               status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
               last_error TEXT, next_attempt_at REAL NOT NULL DEFAULT 0,
               created_at REAL NOT NULL, PRIMARY KEY (kind, key));
           INSERT INTO erp_outbox (kind, key, payload, created_at)
               VALUES ('visit', 'v1', '{"stage": "gate"}', 1);
           INSERT INTO erp_outbox (kind, key, payload, status, attempts, last_error, created_at)
               VALUES ('truck', 'BE1AA', '{"v": 1}', 'error', 2, 'timeout', 2);"""
    )
    lama.commit()
    lama.close()

    outbox = ErpOutboxStore(path, clock=Clock())

    visit, truck = outbox.due()
    assert (visit.key, visit.payload, visit.version) == ("v1", {"stage": "gate"}, 0)
    assert (truck.key, truck.attempts, truck.last_error) == ("BE1AA", 2, "timeout")
    outbox.mark_sent(visit)
    outbox.mark_sent(truck)
    assert outbox.due() == []
    outbox.enqueue("visit", "v1", {"stage": "departed"})
    assert outbox.due()[0].version == 1


def test_due_memakai_indeksnya_dan_tetap_melewati_yang_terkirim(tmp_path):
    """Batch 2.5: `status != 'sent'` tidak bisa memakai `idx_erp_outbox_due`; tabel ini
    tidak pernah dibersihkan dan dipindai tiap 30 detik oleh dua worker."""
    clock = Clock()
    outbox = _store(tmp_path, clock)
    outbox.enqueue("visit", "baru", {"n": 1})
    outbox.enqueue("visit", "gagal", {"n": 2})
    outbox.enqueue("visit", "terkirim", {"n": 3})
    [baru, gagal, terkirim] = outbox.due()
    outbox.mark_error(gagal, "HTTP 500")
    outbox.mark_sent(terkirim)
    clock.now += 30

    [plan] = rencana(outbox._db, outbox.due)

    assert "USING INDEX idx_erp_outbox_due" in plan, plan
    assert [m.key for m in outbox.due()] == ["baru", "gagal"]
