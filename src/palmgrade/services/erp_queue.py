"""Turns console rows into messages for AutoERP and queues them (contract §4).

One place builds them, so the live triggers and the daily resend can never drift
apart: both call `visit()`, and both therefore send the same thing for the same
visit. Nothing here talks HTTP — the outbox worker does that later, possibly
after a power cut.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from ..domain import erp_messages
from ..integrations.erp.outbox_store import ErpOutboxStore
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)


class ErpQueue:
    def __init__(
        self,
        store: ConsoleStore,
        outbox: ErpOutboxStore,
        *,
        site: str = "",
        detail_url_for: Callable[[str], str | None] = lambda visit_id: None,
    ) -> None:
        self._store = store
        # Public: the worker that drains it is built from the same queue object,
        # so there is one outbox in the process and no way to wire a second.
        self.outbox = outbox
        self._site = site
        # Defaults to "no detail page" so every existing construction site and
        # test keeps working unchanged. console_main.py wires the real one only
        # when R2 is configured (see domain/visit_manifest.detail_url_for).
        self._detail_url_for = detail_url_for
        # Held from reading the store to queueing the message (`visit`). One
        # instance per console process (built once in `routes/console_deps.py`),
        # so every trigger shares it.
        self._visit_lock = threading.Lock()

    def truck(self, plate_number: str) -> None:
        """Interface B: a plate first seen at the mill goes up to AutoERP."""
        key, payload = erp_messages.truck_message(plate_number)
        self.outbox.enqueue(erp_messages.TRUCK, key, payload)

    def visit(self, weighing_id: str, *, tz: ZoneInfo | None = None) -> bool:
        """Interface C: the whole visit as we know it now. False when there is
        nothing to send yet.

        The payload is rebuilt from the store on every call rather than patched,
        and one lock covers read, build and enqueue. That lock is what guarantees
        the queued message never carries older state than the store: without it,
        two calls on two threads (two late bunches, or a release racing an
        ingest) could read in one order and enqueue in the other, leaving the
        recap without the last bunch.
        """
        with self._visit_lock:
            return self._queue_visit(weighing_id, tz)

    def _queue_visit(self, weighing_id: str, tz: ZoneInfo | None) -> bool:
        visit = self._store.visit(weighing_id)
        if not visit or not visit.get("entered_at"):
            # `weighing.time_in` dates the ticket in AutoERP; without it there is
            # no visit to send. The daily resend picks it up once there is.
            return False

        # Every line that unloaded this truck, summed (2026-10-01): a truck on three
        # lines is one visit, and AutoERP pays on its whole recap.
        grading = self._store.grading_counts_for_visit(visit["id"])
        if grading and (url := self._detail_url_for(visit["id"])):
            grading = grading | {"detail_url": url}
        emitted_at = datetime.now(tz).isoformat() if tz else datetime.now().astimezone().isoformat()
        key, payload = erp_messages.visit_message(
            visit, grading, site=self._site, emitted_at=emitted_at
        )
        self.outbox.enqueue(erp_messages.VISIT, key, payload)
        return True

    def visits_on(self, work_date: str, *, tz: ZoneInfo | None = None) -> int:
        """Every visit of one working day, queued again (the daily resend, §5)."""
        queued = sum(self.visit(wid, tz=tz) for wid in self._store.weighing_ids_on(work_date))
        if queued:
            logger.info("Visits re-queued for %s: %s", work_date, queued)
        return queued
