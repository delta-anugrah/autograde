"""Gate times and the unloading queue (rules 36 and 37). Included by `routes/console.py`.

A module of its own because `routes/console.py` stays under 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). The two routers are included at the exact spots the
routes used to sit, so `console.router` keeps every path in the same order
(`tests/unit/test_console_router_peta.py`) and every test that mounts `console.router`
still gets them.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..domain.operator_error import InvalidInput, OperatorError
from ..schemas.console_schema import ArrivalBody, DepartureBody
from .console_deps import Gate, Operator, Service, _operator_error

gerbang_router = APIRouter(tags=["console"])
antrean_bongkar_router = APIRouter(tags=["console"])


@gerbang_router.post("/api/console/arrivals")
def console_arrival(gate: Gate, operator: Operator, payload: ArrivalBody) -> dict:
    """Scan 1 (2026-09-30): the truck reached the gate. Recorded on this PC only.

    Every outcome of a readable request is 200 with `hasil`, like the other scan lanes:
    a truck scanned twice, or one still in the yard, is the gate doing its job. A plain
    `def` (rule 30): it only does synchronous SQLite work, so it runs in the thread pool.
    """
    try:
        return gate.arrive(payload.qr or "", payload.at)
    except (OperatorError, ValueError) as exc:
        raise _operator_error(400, exc) from exc


@gerbang_router.post("/api/console/arrivals/{arrival_id}/cancel")
def console_arrival_cancel(arrival_id: str, gate: Gate, operator: Operator) -> dict:
    """"Batal datang" (2026-10-03): take back an arrival whose truck will not be weighed.

    `dibatalkan` or `tidak_ada` (already weighed in, already cancelled, unknown id), both
    200: a second press or a race with the weigh-in is not an error. Never reaches AutoERP.
    """
    return gate.cancel_arrival(arrival_id, oleh=operator["email"], nama=operator.get("full_name"))


@gerbang_router.post("/api/console/departures")
def console_departure(gate: Gate, operator: Operator, payload: DepartureBody) -> dict:
    """Scan 4 (2026-09-30): the truck leaves the gate. Recorded on this PC only.

    A truck not yet weighed out is answered `belum_timbang_kosong` and nothing is
    written: that warning is what scan 4 is for.
    """
    try:
        return gate.leave(payload.qr or "", payload.at, weighing_id=(payload.weighing_id or "").strip() or None)
    except (OperatorError, ValueError) as exc:
        raise _operator_error(400, exc) from exc


@antrean_bongkar_router.post("/api/console/unloading-queue/{weighing_id}/assign")
async def unloading_queue_assign(weighing_id: str, service: Service, operator: Operator) -> dict:
    """"Tugaskan sekarang" on the unloading queue: this truck onto the free lines now.

    409 when the queue changed since the screen drew it (`bukan_antrean`) or no line is
    free (`line_semua_terpakai`): the state moved, the request itself was fine.
    """
    try:
        return {"dipasang": await service.pasang_dari_antrean(weighing_id)}
    except InvalidInput as exc:
        raise _operator_error(409, exc) from exc


@antrean_bongkar_router.post("/api/console/unloading-queue/{weighing_id}/skip")
def unloading_queue_skip(weighing_id: str, service: Service, operator: Operator) -> dict:
    """"Lewati": a truck that will not unload leaves the unloading queue."""
    try:
        service.lewati_antrean(weighing_id, oleh=operator["email"])
    except InvalidInput as exc:
        raise _operator_error(409, exc) from exc
    return {"weighing_id": weighing_id, "dilewati": True}
