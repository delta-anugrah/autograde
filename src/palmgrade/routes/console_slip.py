"""Printable grading slip per truck (batch 5.9). Included by `routes/console.py`.

A module of its own because `routes/console.py` stays under 1,000 lines
(`tests/unit/test_ukuran_berkas.py`).
"""
from __future__ import annotations

from fastapi import APIRouter

from ..domain.operator_error import SLIP_MATI, OperatorError
from ..schemas.console_schema import SlipBody
from .console_deps import Operator, Slip, Support, _operator_error

slip_router = APIRouter(tags=["console"])


@slip_router.get("/api/console/slip")
def grading_slip(slip: Slip, operator: Operator, work_date: str, truck_id: str) -> dict:
    """One truck's slip for one working day, for every account while support has it on.

    403 `slip_mati` while it is off: the screen hiding the Print button is only tidiness
    (rule 21). 404 `slip_tidak_ada` for a truck with no bunch that day. `def`, not
    `async def`: it reads the day's recap from SQLite (rule 30).
    """
    try:
        return slip.slip(work_date, truck_id)
    except OperatorError as exc:
        raise _operator_error(403 if exc.code == SLIP_MATI else 404, exc) from exc


@slip_router.get("/api/console/dev/slip")
def slip_switch(slip: Slip, operator: Support) -> dict:
    return {"aktif": slip.aktif()}


@slip_router.post("/api/console/dev/slip")
def save_slip_switch(slip: Slip, operator: Support, payload: SlipBody) -> dict:
    return slip.atur(payload.aktif)
