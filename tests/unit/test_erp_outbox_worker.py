"""Draining the AutoERP outbox (contract §5, backlog AG-4).

Pinned: what each of the three outcomes does to the queue. Getting this wrong
either drops a message AutoERP never received, or hammers a dead ERP with a
whole batch every 30 seconds.
"""
from __future__ import annotations

import asyncio

import httpx

from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.services.status_sinkron import StatusSinkron
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker, OutboxHandler

ERP = "http://erp.local"
METHOD = "erpnext.palm_mill.api.upsert_truck"


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _worker(tmp_path, handler, on_sent=None):
    clock = Clock()
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db", clock=clock)
    client = ErpClient(ERP, "k", "s", transport=httpx.MockTransport(handler))
    delivered: list[tuple[str, object]] = []
    handlers = {
        "truck": OutboxHandler(
            method=METHOD,
            on_sent=on_sent or (lambda key, message: delivered.append((key, message))),
        )
    }
    return ErpOutboxWorker(outbox, client, handlers), outbox, clock, delivered


def test_a_delivered_message_is_marked_sent_and_handed_to_its_handler(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"name": "BE 1 AA", "supplier": None}})

    worker, outbox, _, delivered = _worker(tmp_path, handler)
    outbox.enqueue("truck", "BE1AA", {"plate_number": "BE 1 AA"})

    assert asyncio.run(worker.drain_once()) == 1
    assert delivered == [("BE1AA", {"name": "BE 1 AA", "supplier": None})]
    assert outbox.due() == []


def test_an_unreachable_autoerp_holds_the_whole_batch(tmp_path):
    """The rest of the batch would only burn its backoff against a dead ERP."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, text="service unavailable")

    worker, outbox, clock, _ = _worker(tmp_path, handler)
    outbox.enqueue("truck", "BE1AA", {"plate_number": "BE 1 AA"})
    clock.now += 1
    outbox.enqueue("truck", "BE2BB", {"plate_number": "BE 2 BB"})

    assert asyncio.run(worker.drain_once()) == 0
    assert len(calls) == 1
    # The second was never tried, so it is still due; the first is backing off.
    assert [m.key for m in outbox.due()] == ["BE2BB"]


def test_a_rejected_message_keeps_its_reason_and_the_batch_moves_on(tmp_path):
    """One malformed payload must not starve the messages queued behind it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if b"!!!" in request.content:
            return httpx.Response(
                417,
                json={
                    "exc_type": "ValidationError",
                    "exception": "frappe.exceptions.ValidationError: Nomor polisi harus berisi huruf",
                },
            )
        return httpx.Response(200, json={"message": {"name": "BE 2 BB"}})

    worker, outbox, clock, delivered = _worker(tmp_path, handler)
    outbox.enqueue("truck", "BAD", {"plate_number": "!!!"})
    clock.now += 1
    outbox.enqueue("truck", "BE2BB", {"plate_number": "BE 2 BB"})

    assert asyncio.run(worker.drain_once()) == 1
    assert [key for key, _ in delivered] == ["BE2BB"]

    clock.now += 30
    [held] = outbox.due()
    assert held.key == "BAD"
    assert "Nomor polisi" in held.last_error


def test_a_kind_without_a_handler_is_held_not_sent_blindly(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError(f"nothing should be posted: {request.url}")

    worker, outbox, clock, _ = _worker(tmp_path, handler)
    outbox.enqueue("visit", "v1", {"stage": "gate"})

    assert asyncio.run(worker.drain_once()) == 0

    clock.now += 30
    [held] = outbox.due()
    assert "visit" in held.last_error


def test_a_handler_that_fails_locally_keeps_the_message(tmp_path):
    """AutoERP accepted it, but our own bookkeeping did not land: sending again
    is safe (upserts), losing the link is not."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"name": "BE 1 AA"}})

    def explode(key, message):
        raise RuntimeError("database is locked")

    worker, outbox, clock, _ = _worker(tmp_path, handler, on_sent=explode)
    outbox.enqueue("truck", "BE1AA", {"plate_number": "BE 1 AA"})

    assert asyncio.run(worker.drain_once()) == 0

    clock.now += 30
    [held] = outbox.due()
    # Round 1 fix: same format as the catch-all around `call_method`, so support
    # reading Antrean ERP always sees the exception type, not just its message.
    assert held.last_error == "RuntimeError: database is locked"


# ── batch 2.7: one message's failure is that message's problem ───────────────


def test_a_frappe_500_on_one_payload_does_not_hold_the_others(tmp_path):
    """A handler that crashes on ONE payload used to read as "AutoERP is down" and
    held the whole batch, with Frappe's reason thrown away."""

    def handler(request: httpx.Request) -> httpx.Response:
        if b"RACUN" in request.content:
            return httpx.Response(500, json={"exc_type": "KeyError", "exception": "KeyError: 'counts'"})
        return httpx.Response(200, json={"message": {"name": "ok"}})

    worker, outbox, clock, delivered = _worker(tmp_path, handler)
    outbox.enqueue("truck", "RACUN", {"plate_number": "RACUN"})
    clock.now += 1
    outbox.enqueue("truck", "BE2BB", {"plate_number": "BE 2 BB"})
    clock.now += 1
    outbox.enqueue("truck", "BE3CC", {"plate_number": "BE 3 CC"})

    assert asyncio.run(worker.drain_once()) == 2
    assert [key for key, _ in delivered] == ["BE2BB", "BE3CC"]
    [held] = outbox.failed_rows()
    assert (held["key"], held["attempts"]) == ("RACUN", 1)
    assert "KeyError: 'counts'" in held["last_error"]


def test_a_poison_row_backs_off_and_stays_out_of_the_next_tick(tmp_path):
    """A `ErpServerError` row is held with a 30 s backoff like any other refusal
    (`mark_error`). Two ticks on a fake clock, close to 30 s apart: `due()` compares
    with `<=`, so tick 2 must land strictly inside the window (29 s, not the full
    30) to prove the poison row is skipped rather than tried again right on the
    boundary. On tick 2 it gets NO call at all, while a row queued after it goes
    through normally."""
    calls: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content)
        if b"RACUN" in request.content:
            return httpx.Response(500, json={"exc_type": "KeyError", "exception": "KeyError: 'counts'"})
        return httpx.Response(200, json={"message": {"name": "ok"}})

    worker, outbox, clock, delivered = _worker(tmp_path, handler)
    outbox.enqueue("truck", "RACUN", {"plate_number": "RACUN"})

    assert asyncio.run(worker.drain_once()) == 0  # tick 1: poison row tried once, held
    assert len(calls) == 1
    [held] = outbox.failed_rows()
    assert held["attempts"] == 1

    clock.now += 29  # tick 2, just under 30 s after tick 1
    outbox.enqueue("truck", "BE2BB", {"plate_number": "BE 2 BB"})  # newer row, queued after

    assert asyncio.run(worker.drain_once()) == 1  # tick 2: poison row not yet due
    assert [key for key, _ in delivered] == ["BE2BB"]
    assert len(calls) == 2  # still just the one call from tick 1, plus BE2BB now
    [held] = outbox.failed_rows()
    assert (held["key"], held["attempts"]) == ("RACUN", 1)  # untouched this tick


def test_a_500_page_that_is_not_frappes_still_holds_the_batch(tmp_path):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, text="<html><center>nginx</center></html>")

    worker, outbox, clock, _ = _worker(tmp_path, handler)
    outbox.enqueue("truck", "A", {"plate_number": "A"})
    clock.now += 1
    outbox.enqueue("truck", "B", {"plate_number": "B"})

    assert asyncio.run(worker.drain_once()) == 0
    assert len(calls) == 1
    assert [m.key for m in outbox.due()] == ["B"]


def test_a_500_page_that_is_not_frappes_reads_terputus_on_last_sync(tmp_path):
    """Round 1 fix: a non-Frappe 500 (nginx in front of a dead Frappe) used to raise
    `ErpUnavailable(status=500)`, which `galat_jaringan` did not treat as a network
    failure (only None/502/503/504 did). Last Sync stayed green and even cleared an
    earlier real network failure. It must read `terputus`, like a dead link."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html><center>nginx</center></html>")

    clock = Clock()
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db", clock=clock)
    client = ErpClient(ERP, "k", "s", transport=httpx.MockTransport(handler))
    status = StatusSinkron(None, erp_aktif=True, r2_aktif=False)
    worker = ErpOutboxWorker(
        outbox, client,
        {"truck": OutboxHandler(method=METHOD, on_sent=lambda key, answer: None)},
        status=status,
    )
    outbox.enqueue("truck", "A", {"plate_number": "A"})

    assert asyncio.run(worker.drain_once()) == 0
    assert status.ringkas("erp", antre=1)["keadaan"] == "terputus"


def test_a_200_that_is_not_json_is_recorded_and_backs_off(tmp_path):
    """The reproduced bug: the oldest row was tried first on EVERY tick, never recorded,
    never backed off, and the row behind it never moved. Now every try is recorded, the
    head row backs off 30 s, 60 s, 120 s, and the second row gets its turns."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, text="<html><body>Login hotspot</body></html>")

    worker, outbox, clock, _ = _worker(tmp_path, handler)
    outbox.enqueue("truck", "A", {"plate_number": "A"})
    clock.now += 1
    outbox.enqueue("truck", "B", {"plate_number": "B"})

    for _ in range(5):                      # five ticks, 30 s apart
        assert asyncio.run(worker.drain_once()) == 0
        clock.now += 30

    tries = {row["key"]: row["attempts"] for row in outbox.failed_rows()}
    assert tries == {"A": 3, "B": 2}
    assert len(calls) == 5
    assert all("HTTP 200" in row["last_error"] for row in outbox.failed_rows())


class _BrokenClient:
    """A bug on our side of the wire for one payload: not an ErpError at all."""

    async def call_method(self, method, payload):
        if payload["plate_number"] == "A":
            raise RuntimeError("client bug")
        return {"name": payload["plate_number"]}


def test_an_unexpected_error_for_one_message_is_recorded_and_the_batch_goes_on(tmp_path):
    clock = Clock()
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db", clock=clock)
    delivered: list[str] = []
    worker = ErpOutboxWorker(
        outbox, _BrokenClient(),
        {"truck": OutboxHandler(method=METHOD, on_sent=lambda key, answer: delivered.append(key))},
    )
    outbox.enqueue("truck", "A", {"plate_number": "A"})
    clock.now += 1
    outbox.enqueue("truck", "B", {"plate_number": "B"})

    assert asyncio.run(worker.drain_once()) == 1
    assert delivered == ["B"]
    [held] = outbox.failed_rows()
    assert (held["key"], held["attempts"]) == ("A", 1)
    assert "RuntimeError: client bug" in held["last_error"]
