"""Tab Status → Antrean line (support, batch 2.4). Mounted ONLY by `console_main.py`.

Modul sendiri, bukan tambahan di `routes/console.py`: berkas itu dipakai banyak
alur kerja sekaligus, dan dua lane ini tidak berbagi apa pun dengannya selain
penjaga `Support`.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..integrations.notifications.line_client import LineUnavailable
from ..services.pantau_antrean_line import PantauAntreanLine
from .console_deps import Support, _operator_error, get_pantau_antrean_line

router = APIRouter(tags=["console"])

PantauAntrean = Annotated[PantauAntreanLine, Depends(get_pantau_antrean_line)]


@router.get("/api/console/dev/antrean/line")
async def antrean_line(pantau: PantauAntrean, operator: Support) -> dict:
    """Satu baris per line. Line mati atau menolak kunci tetap 200, dengan sebabnya."""
    return await pantau.ringkasan()


@router.post("/api/console/dev/antrean/line/{line_code}/kirim-ulang")
async def kirim_ulang_antrean_line(line_code: str, pantau: PantauAntrean, operator: Support) -> dict:
    """404 line tak dikenal; 502 line mati (`line_tidak_menjawab`) atau menolak (`line_menolak`)."""
    try:
        return await pantau.kirim_ulang(line_code, oleh=operator["email"])
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc
