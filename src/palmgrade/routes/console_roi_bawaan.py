"""Settings, detection area box: the PC's own box (support, 2026-10-05). Mounted ONLY by
`console_main.py`.

Its own module, not one more route in `routes/console.py`: that file is at its size limit,
and this lane shares nothing with it but the `Support` guard and the line list.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..services.roi_bawaan import roi_bawaan
from .console_deps import Service, Support

router = APIRouter(tags=["console"])


@router.get("/api/console/dev/roi-bawaan")
async def kotak_bawaan_pc(service: Service, operator: Support) -> dict:
    """`roi_x1..roi_y2` the lines use while the console sets none, read from the first line
    that answers; all None when none does. Always 200: the screen words the unknown case."""
    return await roi_bawaan(service.lines, service.line_client)
