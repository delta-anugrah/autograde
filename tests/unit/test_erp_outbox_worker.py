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
    assert "database is locked" in held.last_error
