"""`GET /api/console/scale/live`: the weight on the weighbridge now (2026-10-06).

Mounted only by `console_main.py`. A module of its own so `routes/console.py` stays
under 1,000 lines. The screen polls it every second on every tab; the answer is an
in-memory snapshot (no SQLite), so the poll costs nothing. Like every poll it does
not renew the session (rule 19): `require_operator` only reads it.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..services.timbangan_live import TimbanganLive
from .console_deps import Operator, get_timbangan_live

router = APIRouter(tags=["console"])

Live = Annotated[TimbanganLive, Depends(get_timbangan_live)]


@router.get("/api/console/scale/live")
async def timbangan_live(live: Live, operator: Operator) -> dict:
    """`{keadaan, kg, umur_detik}`; `kg` is null unless the number may be shown."""
    return live.snapshot()
