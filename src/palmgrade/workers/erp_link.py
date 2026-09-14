"""Composition of the AutoERP link.

One place decides whether the link exists at all: with `ERP_URL` empty there is
no client, no worker and no traffic. The operator screen must never depend on
AutoERP being reachable.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from ..core.config import Settings
from ..domain import erp_messages
from ..domain.erp_master import supplier_id_for
from ..domain.plate import truck_id_for
from ..integrations.erp.client import ErpClient
from ..repositories.console_repository import ConsoleStore
from ..services.erp_queue import ErpQueue
from .erp_outbox_worker import ErpOutboxWorker, OutboxHandler
from .master_data_worker import MasterDataWorker
from .visit_resend_worker import VisitResendWorker

logger = logging.getLogger(__name__)

UPSERT_TRUCK = "erpnext.palm_mill.api.upsert_truck"
UPSERT_VISIT = "erpnext.palm_mill.api.upsert_visit"


class Worker(Protocol):
    async def run_loop(self) -> None: ...


def truck_linked(store: ConsoleStore) -> Callable[[str, Any], None]:
    """Record what AutoERP answered for a truck sent up (contract §4.B).

    `erp_name` is what the visit is sent under later, so it matters more than it
    looks. AutoERP also answers with the owner it already had, which saves the
    console from showing the truck ownerless until it is next touched upstream.
    """

    def record(key: str, answer: Any) -> None:
        answer = answer or {}
        supplier = answer.get("supplier")
        store.link_truck(
            truck_id_for(key),
            answer["name"],
            supplier_id_for(supplier) if supplier else None,
        )

    return record


def visit_recorded(store: ConsoleStore) -> Callable[[str, Any], None]:
    """Keep what AutoERP answered for a visit.

    The Weighbridge Ticket is the trace from a weighbridge row at the mill to the
    receipt in the ledger. The `note` is the part that used to be dropped, and it is
    the part a human needs: AutoERP never rewrites a finalised ticket, so a late
    grading change is acknowledged as `revised` with a comment on its side — and the
    mill kept marking that send simply "delivered".
    """

    def record(key: str, answer: Any) -> None:
        answer = answer or {}
        note = answer.get("note")
        store.record_visit_answer(
            key, ticket=answer.get("ticket"), status=answer.get("status"), note=note
        )
        if note or answer.get("revised"):
            logger.warning(
                "AutoERP answer needs a look for visit %s: %s (ticket %s, status %s)",
                key,
                note or "grading revised after finalisation",
                answer.get("ticket"),
                answer.get("status"),
            )

    return record


def build_erp_workers(settings: Settings, store: ConsoleStore, queue: ErpQueue) -> list[Worker]:
    """Every background task that talks to AutoERP, or none at all."""
    if not settings.erp_url:
        logger.info("AutoERP link off: ERP_URL is empty")
        return []

    client = ErpClient(settings.erp_url, settings.erp_api_key, settings.erp_api_secret)
    handlers = {
        erp_messages.TRUCK: OutboxHandler(method=UPSERT_TRUCK, on_sent=truck_linked(store)),
        erp_messages.VISIT: OutboxHandler(method=UPSERT_VISIT, on_sent=visit_recorded(store)),
    }
    return [
        MasterDataWorker(store, client, interval_s=settings.console_sync_interval_s),
        ErpOutboxWorker(queue.outbox, client, handlers),
        VisitResendWorker(queue, store, ZoneInfo(settings.factory_tz)),
    ]
