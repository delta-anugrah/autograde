"""Lane antrean janjang di sisi LINE (batch 2.4, 2026-09-28), dipanggil konsol.

- `GET  /internal/outbox`: ringkasan untuk tab Status → Antrean line.
- `POST /internal/outbox/requeue`: Kirim Ulang, semua baris jatuh tempo sekarang.
  Dipindah dari `routes/internal.py` dengan URL dan bentuk jawaban yang sama.

Dirakit lewat `buat_router()` dengan dependensi disuntik, seperti
`routes/internal_bahaya.py`: `routes/internal.py` menarik torch, dan lane ini harus
teruji di CI. Kedua rute `def` biasa, bukan `async`: FastAPI menjalankannya di
threadpool, jadi SQLite tidak menahan loop yang melayani `/internal/status` tiap detik.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends

from ..core.config import Settings
from ..schemas.internal_schema import OutboxRequeueResponse
from ..services.antrean_line import AntreanLine
from .penjaga_rahasia import penjaga_internal


def buat_router(
    *, settings: Callable[[], Settings], antrean: Callable[[], AntreanLine]
) -> APIRouter:
    """Router `/internal/outbox*` untuk satu proses line, di balik `INTERNAL_SECRET`."""
    router = APIRouter(
        prefix="/internal",
        tags=["internal"],
        dependencies=[Depends(penjaga_internal(settings))],
    )

    @router.get("/outbox")
    def ringkasan_outbox() -> dict[str, Any]:
        return antrean().ringkasan()

    @router.post("/outbox/requeue", response_model=OutboxRequeueResponse)
    def outbox_requeue() -> OutboxRequeueResponse:
        return OutboxRequeueResponse(requeued=antrean().kirim_ulang())

    return router
