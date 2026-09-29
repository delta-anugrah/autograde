"""Drains the AutoERP outbox (contract §5, backlog AG-4).

Four outcomes, and the difference between them is what keeps the queue honest:

- **delivered**: the handler records AutoERP's answer, the row is done.
- **refused or crashed on this payload** (4xx, or a 5xx carrying Frappe's error
  envelope): kept with AutoERP's reason and retried on the backoff. One bad
  payload must never starve the messages queued behind it.
- **unreachable** (network, gateway, anything that is not Frappe answering): the
  batch stops. The rest would only burn their backoff against an ERP that is
  down, and they are all still queued.
- **anything else raised for one message**: recorded and backed off like a
  refusal (batch 2.7). Letting it escape `drain_once` retried that same oldest
  row first on every tick, with no backoff, while nothing behind it moved.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..integrations.erp.client import (
    ErpClient,
    ErpError,
    ErpRejected,
    ErpServerError,
    ErpUnavailable,
    galat_jaringan,
)
from ..integrations.erp.outbox_store import ErpOutboxStore, OutboxMessage
from ..services.status_sinkron import StatusSinkron

logger = logging.getLogger(__name__)

_INTERVAL_S = 30
# Kunci AutoERP ditolak: tidak ada kiriman yang akan sampai, apa pun isinya.
_KUNCI_DITOLAK = (401, 403)
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
        status: StatusSinkron | None = None,
    ) -> None:
        self._outbox = outbox
        self._client = client
        self._handlers = handlers
        self._interval_s = interval_s
        self._batch = batch
        self._status = status

    async def run_loop(self) -> None:
        logger.info("ErpOutboxWorker started, every %ss", self._interval_s)
        while True:
            try:
                await self.drain_once()
            except Exception:
                logger.exception("Outbox drain failed; retrying next tick")
            await asyncio.sleep(self._interval_s)

    def _catat_gagal_lokal(self, message: OutboxMessage, exc: Exception, *, apa: str) -> None:
        """Satu format untuk bug di sisi kita: nama tipe exception + pesannya, supaya
        Antrean ERP selalu menyebut tipenya, bukan cuma teks yang kebetulan dibawa
        exception itu (mis. `KeyError` membawa `''` sebagai pesan)."""
        logger.exception("%s %s %s failed", apa, message.kind, message.key)
        self._outbox.mark_error(message, f"{type(exc).__name__}: {exc}")

    def _catat_galat(self, exc: ErpError) -> None:
        """Last Sync: apa arti galat satu kiriman untuk sambungannya.

        - jaringan (tanpa jawaban, gateway mati): putus, sampai ada jawaban dari mana pun;
        - 401/403: kunci AutoERP ditolak, tidak ada yang akan sampai: putus;
        - sisanya (417, 404, 500, ...): AutoERP menjawab, ISI pesan ini yang ditolak atau
          memicu galat. Pesannya terlihat di tab Antrean ERP, bukan di warna sambungan;
          server yang benar-benar rusak ketahuan dari ping tiap menit.
        """
        if self._status is None:
            return
        if galat_jaringan(exc):
            self._status.gagal("erp", "kirim", str(exc), jaringan=True)
        elif exc.status in _KUNCI_DITOLAK:
            self._status.gagal("erp", "kirim", str(exc))
        else:
            self._status.berhasil("erp", "kirim", sinkron=False)

    async def drain_once(self) -> int:
        """One batch. Returns how many messages AutoERP accepted. Never raises for one message."""
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
                self._catat_galat(exc)
                break
            except (ErpRejected, ErpServerError) as exc:
                logger.error("AutoERP refused or failed on %s %s: %s", message.kind, message.key, exc)
                self._outbox.mark_error(message, str(exc))
                self._catat_galat(exc)
                continue
            except Exception as exc:
                self._catat_gagal_lokal(message, exc, apa="Sending")
                continue

            try:
                handler.on_sent(message.key, answer)
            except Exception as exc:
                # AutoERP has it; our own bookkeeping did not land. Sending again
                # is safe (every handler upserts); losing the answer is not.
                self._catat_gagal_lokal(message, exc, apa="Recording")
                continue

            self._outbox.mark_sent(message)
            delivered += 1
            if self._status is not None:
                self._status.berhasil("erp", "kirim", sinkron=True)

        if delivered:
            logger.info("AutoERP outbox: %s message(s) delivered", delivered)
        return delivered
