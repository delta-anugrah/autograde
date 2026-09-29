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
from ..domain.jawaban_kunjungan import TANPA_NOMOR, KonteksKunjungan, jam_masuk, kabar_baru, pesan_log
from ..domain.plate import truck_id_for
from ..integrations.erp.client import ErpClient
from ..repositories.console_repository import ConsoleStore
from ..services.erp_queue import ErpQueue
from ..services.status_sinkron import StatusSinkron
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


def visit_recorded(store: ConsoleStore, *, tz: ZoneInfo) -> Callable[[str, Any], None]:
    """Keep what AutoERP answered for a visit.

    The Weighbridge Ticket is the trace from a weighbridge row at the mill to the
    receipt in the ledger. AutoERP never rewrites a finalised ticket, so a late
    grading change comes back as `revised` + a note, and the ticket keeps the numbers
    it was booked with. Only answers a human must act on reach the Log tab (batch 2.3):
    a finalised ticket that received different numbers, or a cancelled one, once per
    change of AutoERP's answer. "visit unchanged" is what every daily resend of a
    finalised ticket answers; logging it as a WARNING buried the one line that
    mattered. The same "grading revised" answered again by a resend is not a new
    change either (see `domain/jawaban_kunjungan.kabar_baru`). `tz` is the factory's:
    the weigh-in time is written as the Timbangan row shows it.
    """

    def record(key: str, answer: Any) -> None:
        answer = answer or {}
        note = answer.get("note")
        sebelumnya = (store.weighing(key) or {}).get("erp_note")
        store.record_visit_answer(
            key, ticket=answer.get("ticket"), status=answer.get("status"), note=note
        )
        golongan = kabar_baru(note, revised=bool(answer.get("revised")), sebelumnya=sebelumnya)
        if golongan is None:
            if note:
                logger.info("AutoERP answer for visit %s: %s", key, note)
            return
        logger.warning(pesan_log(golongan, _konteks(store, key, answer, tz)))

    return record


def _konteks(store: ConsoleStore, key: str, answer: dict[str, Any], tz: ZoneInfo) -> KonteksKunjungan:
    """Truck, line, weigh-in time and current recap of this visit, for one Log tab line."""
    visit = store.visit(key) or {}
    assignment_id = visit.get("assignment_id")
    grading = (store.grading_counts(assignment_id) if assignment_id else None) or {}
    return KonteksKunjungan(
        plat=visit.get("plate_number") or "-",
        line=grading.get("line_code") or "-",
        masuk=jam_masuk(visit.get("entered_at"), tz),
        tiket=answer.get("ticket") or visit.get("erp_ticket") or TANPA_NOMOR,
        catatan=answer.get("note") or "grading revised after finalisation",
        janjang=grading.get("total"),
        mentah=grading.get("rej"),
    )


def outbox_handlers(store: ConsoleStore, *, tz: ZoneInfo) -> dict[str, OutboxHandler]:
    """What each kind of message is POSTed to, and who records the answer.

    One definition shared by `build_erp_workers` and the tests that drive the real
    worker, so a test cannot wire a handler the console does not.
    """
    return {
        erp_messages.TRUCK: OutboxHandler(method=UPSERT_TRUCK, on_sent=truck_linked(store)),
        erp_messages.VISIT: OutboxHandler(method=UPSERT_VISIT, on_sent=visit_recorded(store, tz=tz)),
    }


def build_erp_workers(
    settings: Settings,
    store: ConsoleStore,
    queue: ErpQueue,
    *,
    status: StatusSinkron | None = None,
) -> list[Worker]:
    """Every background task that talks to AutoERP, or none at all."""
    if not settings.erp_url:
        logger.info("AutoERP link off: ERP_URL is empty")
        return []

    client = ErpClient(settings.erp_url, settings.erp_api_key, settings.erp_api_secret)
    tz = ZoneInfo(settings.factory_tz)
    return [
        MasterDataWorker(store, client, interval_s=settings.console_sync_interval_s, status=status),
        ErpOutboxWorker(queue.outbox, client, outbox_handlers(store, tz=tz), status=status),
        VisitResendWorker(queue, store, tz),
    ]
