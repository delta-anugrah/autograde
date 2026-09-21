"""When the console sends a visit (contract §4.C).

Three moments, all of them things that happen anyway: the gate weighing, the
truck leaving its line, and the weigh-out. Nothing here asks the operator to
remember an extra step.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from palmgrade.core.config import Settings
from palmgrade.domain.erp_master import supplier_row, truck_row
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.visit_manifest_worker import VisitManifestWorker

PLATE = "BE 8821 KL"
WIB = ZoneInfo("Asia/Jakarta")


class FakeLineClient:
    """The line is a collaborator; the visit lane must not depend on it."""

    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...


class FakeUploader:
    """The manifest lane only needs `.enqueue()` and `.outbox` to prove wiring;
    nothing here ever calls `put_bytes` in these tests (no `drain_once()`)."""

    def put_bytes(self, body, r2_key, *, content_type) -> None: ...


def _service(
    tmp_path, *, linked: bool = False, manifest: VisitManifestWorker | None = None
) -> tuple[ConsoleService, ErpOutboxStore]:
    store = ConsoleStore(tmp_path / "console.db")
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    if linked:
        store.upsert_supplier(supplier_row({"name": "KUD Sumber Makmur", "supplier_group": "Plasma"}))
        store.upsert_truck(
            truck_row({"name": PLATE, "plate_number": PLATE, "supplier": "KUD Sumber Makmur"})
        )
    detail_url_for = (
        (lambda visit_id: f"https://captures.smagri.id/viewer.html?visit={visit_id}")
        if manifest is not None
        else (lambda visit_id: None)
    )
    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"),
        store,
        FakeLineClient(),
        erp_queue=ErpQueue(
            store, outbox, site="PT Sawit Rambang Lestari", detail_url_for=detail_url_for
        ),
        manifest_queue=manifest,
    )
    return service, outbox


def _service_with_manifest(tmp_path) -> tuple[ConsoleService, ErpOutboxStore, VisitManifestWorker]:
    store = ConsoleStore(tmp_path / "console.db")
    manifest = VisitManifestWorker(
        store,
        ErpOutboxStore(tmp_path / "manifest_outbox.db"),
        FakeUploader(),
        public_url="https://captures.smagri.id",
        viewer_html=tmp_path / "viewer.html",
        clock=lambda: "2026-09-16T09:00:00+07:00",
    )
    store.upsert_supplier(supplier_row({"name": "KUD Sumber Makmur", "supplier_group": "Plasma"}))
    store.upsert_truck(
        truck_row({"name": PLATE, "plate_number": PLATE, "supplier": "KUD Sumber Makmur"})
    )
    outbox = ErpOutboxStore(tmp_path / "erp_outbox.db")
    service = ConsoleService(
        replace(Settings(), factory_tz="Asia/Jakarta"),
        store,
        FakeLineClient(),
        erp_queue=ErpQueue(
            store,
            outbox,
            site="PT Sawit Rambang Lestari",
            detail_url_for=lambda visit_id: f"https://captures.smagri.id/viewer.html?visit={visit_id}",
        ),
        manifest_queue=manifest,
    )
    return service, outbox, manifest


def _now() -> str:
    return datetime.now(WIB).isoformat()


def _weigh(service: ConsoleService, **over) -> dict:
    payload = {
        "ref": "SCL-1",
        "plate_number": PLATE,
        "entered_at": _now(),
        "gross_kg": 14560,
    } | over
    return asyncio.run(service.record_weighing(payload))


def _visits(outbox: ErpOutboxStore) -> list:
    return [m for m in outbox.due() if m.kind == "visit"]


def test_the_gate_weighing_queues_the_visit(tmp_path):
    service, outbox = _service(tmp_path, linked=True)

    ticket = _weigh(service)

    [visit] = _visits(outbox)
    assert visit.key == ticket["id"]
    assert visit.payload["stage"] == "gate"
    assert visit.payload["weighing"]["gross_kg"] == 14560.0
    assert "tare_kg" not in visit.payload["weighing"]


def test_the_weigh_out_replaces_it_with_the_tare(tmp_path):
    """Same visit, same queue row: the second send carries the whole state."""
    service, outbox = _service(tmp_path, linked=True)
    _weigh(service)

    _weigh(service, gross_kg=None, tare_kg=5400, exited_at=_now())

    [visit] = _visits(outbox)
    assert visit.payload["stage"] == "departed"
    assert visit.payload["weighing"]["tare_kg"] == 5400.0
    assert visit.payload["weighing"]["gross_kg"] == 14560.0


def test_releasing_the_truck_queues_its_grading(tmp_path):
    """The line assignment closing is what says "these bunches are that truck's"."""
    service, outbox = _service(tmp_path, linked=True)
    ticket = _weigh(service)
    assignment = asyncio.run(service.assign_truck("line-1", truck_id_for(PLATE)))
    for n, (status, tp) in enumerate([("ACC", None), ("ACC", 0.91), ("REJ", None)], start=1):
        service.ingest(
            {
                "event_id": f"ev-{n}",
                "machine_id": service.lines[0].machine_id,
                "timestamp": _now(),
                "ripeness_status": status,
                "ripeness_confidence": 0.9,
                "capture_type": "auto",
                "image_path": None,
                "truck_id": truck_id_for(PLATE),
                "assignment_id": assignment["assignment_id"],
                "prediction": "Acc" if status == "ACC" else "Rej",
                "tp_status": "PASS" if tp else None,
                "tp_confidence": tp,
            }
        )

    asyncio.run(service.release_truck("line-1"))

    [visit] = _visits(outbox)
    assert visit.key == ticket["id"]
    assert visit.payload["stage"] == "grading"
    assert visit.payload["grading"]["assignment_id"] == assignment["assignment_id"]
    assert visit.payload["grading"]["counts"] == {
        "total": 3, "acc": 2, "rej": 1, "mentah": 1, "tangkai_panjang": 1, "manual_reject": 0,
    }


def test_releasing_the_truck_queues_the_manifest_and_the_detail_url(tmp_path):
    """The manifest enqueue and the ERP enqueue are independent — a mill with R2
    configured gets both the per-truck page and a `detail_url` pointing at it."""
    service, outbox, manifest = _service_with_manifest(tmp_path)
    ticket = _weigh(service)
    assignment = asyncio.run(service.assign_truck("line-1", truck_id_for(PLATE)))
    service.ingest(
        {
            "event_id": "ev-1",
            "machine_id": service.lines[0].machine_id,
            "timestamp": _now(),
            "ripeness_status": "ACC",
            "ripeness_confidence": 0.9,
            "capture_type": "auto",
            "image_path": None,
            "truck_id": truck_id_for(PLATE),
            "assignment_id": assignment["assignment_id"],
            "prediction": "Acc",
            "tp_status": None,
            "tp_confidence": None,
        }
    )

    asyncio.run(service.release_truck("line-1"))

    [visit] = _visits(outbox)
    assert visit.payload["grading"]["detail_url"] == f"https://captures.smagri.id/viewer.html?visit={ticket['id']}"
    [queued] = manifest.outbox.due()
    assert (queued.kind, queued.key) == ("manifest", ticket["id"])


def test_a_truck_that_was_never_weighed_queues_nothing(tmp_path):
    """AutoERP dates the ticket from `time_in`; without a weighing there is no
    visit to send yet, and the daily resend will pick it up once there is."""
    service, outbox = _service(tmp_path, linked=True)
    asyncio.run(service.assign_truck("line-1", truck_id_for(PLATE)))

    asyncio.run(service.release_truck("line-1"))

    assert _visits(outbox) == []


def test_a_console_without_the_erp_link_still_weighs(tmp_path):
    """`ERP_URL` empty is the default: the scale lane must not depend on it."""
    store = ConsoleStore(tmp_path / "console.db")
    service = ConsoleService(replace(Settings(), factory_tz="Asia/Jakarta"), store, FakeLineClient())

    assert _weigh(service)["gross_kg"] == 14560.0
