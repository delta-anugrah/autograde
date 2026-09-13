"""Drains the AutoERP outbox (contract §5, backlog AG-4).

Three outcomes, and the difference between them is what keeps the queue honest:

- **delivered** — the handler records AutoERP's answer, the row is done.
- **refused** — kept with AutoERP's reason and retried on the backoff. One bad
  payload must never starve the messages queued behind it.
- **unreachable** — the batch stops. The rest would only burn their backoff
  against an ERP that is down, and they are all still queued.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..integrations.erp.client import ErpClient, ErpRejected, ErpUnavailable
from ..integrations.erp.outbox_store import ErpOutboxStore

logger = logging.getLogger(__name__)

_INTERVAL_S = 30
_BATCH = 50


@dataclass(frozen=True)
class OutboxHandler:
    """What to POST for one kind of message, and what to do with the answer."""

    method: str
    on_sent: Callable[[str, Any], None]


class ErpOutboxWorker:
    def __init__(
        self,
        outbox: ErpOutboxStore,
        client: ErpClient,
        handlers: Mapping[str, OutboxHandler],
        *,
        interval_s: int = _INTERVAL_S,
        batch: int = _BATCH,
    ) -> None:
        self._outbox = outbox
        self._client = client
        self._handlers = handlers
        self._interval_s = interval_s
        self._batch = batch

    async def run_loop(self) -> None:
        logger.info("ErpOutboxWorker started, every %ss", self._interval_s)
        while True:
            try:
                await self.drain_once()
            except Exception:
                logger.exception("Outbox drain failed; retrying next tick")
            await asyncio.sleep(self._interval_s)

    async def drain_once(self) -> int:
        """One batch. Returns how many messages AutoERP accepted."""
        delivered = 0
        for message in self._outbox.due(self._batch):
            handler = self._handlers.get(message.kind)
            if handler is None:
                # Held, not dropped: an older console can queue a kind a newer
                # build knows how to send.
                self._outbox.mark_error(message, f"no handler for kind {message.kind!r}")
                continue

            try:
                answer = await self._client.call_method(handler.method, message.payload)
            except ErpUnavailable as exc:
                logger.warning("AutoERP unreachable, holding the batch: %s", exc)
                self._outbox.mark_error(message, str(exc))
                break
            except ErpRejected as exc:
                logger.error("AutoERP refused %s %s: %s", message.kind, message.key, exc)
                self._outbox.mark_error(message, str(exc))
                continue

            try:
                handler.on_sent(message.key, answer)
            except Exception as exc:
                # AutoERP has it; our own bookkeeping did not land. Sending again
                # is safe (every handler upserts); losing the answer is not.
                logger.exception("Recording %s %s failed", message.kind, message.key)
                self._outbox.mark_error(message, str(exc))
                continue

            self._outbox.mark_sent(message)
            delivered += 1

        if delivered:
            logger.info("AutoERP outbox: %s message(s) delivered", delivered)
        return delivered
