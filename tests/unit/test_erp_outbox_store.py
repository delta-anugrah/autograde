"""The queue of messages waiting for AutoERP (contract §5, backlog AG-4).

Pinned: one row per (kind, key) always holding the newest state, a backoff that
climbs from 30 s to an hour, and that a message replaced while it was on the
wire is never marked as sent.
"""
from __future__ import annotations

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
