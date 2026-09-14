"""Sends yesterday's visits once more, every day (contract §5).

The safety net for whatever the outbox never got: a crash between the weighing
and the queue, a database restored from a backup, a visit whose weighing only
arrived after the truck had gone. AutoERP's handlers are upserts, so replaying a
day costs nothing and closes the gap.

It runs on a plain interval and keeps the day it last sent in `sync_state`, so a
console restarted ten times still resends once.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..repositories.console_repository import ConsoleStore
from ..services.erp_queue import ErpQueue

logger = logging.getLogger(__name__)

RESEND_DAY_KEY = "erp_visit_resend_day"
_INTERVAL_S = 3600


class VisitResendWorker:
    def __init__(
        self,
        queue: ErpQueue,
        store: ConsoleStore,
        tz: ZoneInfo,
        *,
        interval_s: int = _INTERVAL_S,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._queue = queue
        self._store = store
        self._tz = tz
        self._interval_s = interval_s
        self._clock = clock or (lambda: datetime.now(tz))

    async def run_loop(self) -> None:
        logger.info("VisitResendWorker started, checking every %ss", self._interval_s)
        while True:
            try:
                await self.resend_once()
            except Exception:
                logger.exception("Daily visit resend failed; retrying next tick")
            await asyncio.sleep(self._interval_s)

    async def resend_once(self) -> int:
        """Queue yesterday's visits, at most once per mill day."""
        today = self._clock().date()
        if self._store.get_state(RESEND_DAY_KEY) == today.isoformat():
            return 0

        queued = self._queue.visits_on((today - timedelta(days=1)).isoformat(), tz=self._tz)
        self._store.set_state(RESEND_DAY_KEY, today.isoformat())
        return queued
