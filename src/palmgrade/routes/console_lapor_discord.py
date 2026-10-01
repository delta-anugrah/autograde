"""Keadaan lapor Discord untuk tab Log (support, batch 3.5). Mounted ONLY by `console_main.py`.

Modul sendiri, seperti `routes/console_antrean_line.py`: satu lane baca, tidak berbagi
apa pun dengan `routes/console.py` selain penjaga `Support`.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..services.lapor_discord import LaporDiscord
from .console_deps import Support, get_lapor_discord

router = APIRouter(tags=["console"])

Lapor = Annotated[LaporDiscord, Depends(get_lapor_discord)]


@router.get("/api/console/dev/lapor-discord")
def lapor_discord(lapor: Lapor, operator: Support) -> dict:
    """`keadaan` (mati/url_salah/rusak/aktif/tertahan/ditolak) + antrean + galat terakhir.

    `def`, bukan `async`: membaca SQLite, jadi jalan di threadpool (aturan 30).
    """
    return lapor.ringkasan()
