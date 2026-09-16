"""Yesterday's visits go up once more, every day (contract §5).

The safety net for whatever the outbox lost — a crash mid-send, a database
restored from backup, a visit that was never queued because the weighing came
in after the truck had already left. Idempotent upserts make it free.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from palmgrade.domain.erp_master import supplier_row, truck_row
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.visit_resend_worker import VisitResendWorker

WIB = ZoneInfo("Asia/Jakarta")
PLATE = "BE 8821 KL"


class Clock:
    """The working day is a decision, not a wall clock read in three places."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> datetime:
        return self.moment


def _worker(tmp_path, clock: Clock) -> tuple[VisitResendWorker, ConsoleStore, ErpOutboxStore]:
    store = ConsoleStore(tmp_path / "console.db")
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    queue = ErpQueue(store, outbox, site="PT Sawit Rambang Lestari")
    store.upsert_supplier(supplier_row({"name": "KUD Sumber Makmur", "supplier_group": "Plasma"}))
    store.upsert_truck(truck_row({"name": PLATE, "plate_number": PLATE, "supplier": "KUD Sumber Makmur"}))
    return VisitResendWorker(queue, store, WIB, clock=clock), store, outbox


def _weighing(store: ConsoleStore, weighing_id: str, work_date: str) -> None:
    store.upsert_weighing(
        {
            "id": weighing_id,
            "ref": f"SCL-{weighing_id}",
            "plate_number": PLATE,
            "plate_norm": "BE8821KL",
            "truck_id": truck_id_for(PLATE),
            "work_date": work_date,
            "gross_kg": 14560.0,
            "tare_kg": 5400.0,
            "net_kg": 9160.0,
            "entered_at": f"{work_date}T07:41:00+07:00",
            "exited_at": f"{work_date}T08:35:00+07:00",
        }
    )


def test_yesterdays_visits_are_queued_again(tmp_path):
    clock = Clock(datetime(2026, 9, 14, 6, 0, tzinfo=WIB))
    worker, store, outbox = _worker(tmp_path, clock)
    _weighing(store, "w1", "2026-09-13")
    _weighing(store, "w2", "2026-09-12")  # older than yesterday, left alone

    assert asyncio.run(worker.resend_once()) == 1
    assert [m.key for m in outbox.due() if m.kind == "visit"] == ["w1"]


def test_a_second_run_the_same_day_sends_nothing_again(tmp_path):
    """Once a day, not once a tick: the worker wakes up far more often."""
    clock = Clock(datetime(2026, 9, 14, 6, 0, tzinfo=WIB))
    worker, store, _ = _worker(tmp_path, clock)
    _weighing(store, "w1", "2026-09-13")
    asyncio.run(worker.resend_once())

    clock.moment = datetime(2026, 9, 14, 18, 0, tzinfo=WIB)

    assert asyncio.run(worker.resend_once()) == 0


def test_the_next_day_resends_again(tmp_path):
    clock = Clock(datetime(2026, 9, 14, 6, 0, tzinfo=WIB))
    worker, store, _ = _worker(tmp_path, clock)
    _weighing(store, "w1", "2026-09-13")
    asyncio.run(worker.resend_once())
    _weighing(store, "w2", "2026-09-14")

    clock.moment = datetime(2026, 9, 15, 6, 0, tzinfo=WIB)

    assert asyncio.run(worker.resend_once()) == 1


def test_a_day_with_no_weighings_is_not_an_error(tmp_path):
    clock = Clock(datetime(2026, 9, 14, 6, 0, tzinfo=WIB))
    worker, _, outbox = _worker(tmp_path, clock)

    assert asyncio.run(worker.resend_once()) == 0
    assert outbox.due() == []
