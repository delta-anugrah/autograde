"""Working day cutoff (batch 5.11), support only. Included by `routes/console.py`."""
from __future__ import annotations

from fastapi import APIRouter

from ..domain.operator_error import OperatorError
from ..domain.working_day import teks_cutoff
from ..schemas.console_schema import ShiftBody
from .console_deps import Service, Support, _operator_error

shift_router = APIRouter(tags=["console"])


@shift_router.get("/api/console/dev/shift")
def shift_cutoff(service: Service, operator: Support) -> dict:
    return {"cutoff": teks_cutoff(service.hari_kerja.cutoff())}


@shift_router.post("/api/console/dev/shift")
def save_shift_cutoff(service: Service, operator: Support, payload: ShiftBody) -> dict:
    """Applies to the next bunch, ticket and scan; rows already stored keep their date (rule 10)."""
    try:
        return service.hari_kerja.atur(payload.cutoff, oleh=operator["email"])
    except OperatorError as exc:
        raise _operator_error(400, exc) from exc
