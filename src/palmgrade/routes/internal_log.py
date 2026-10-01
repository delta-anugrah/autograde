"""`GET /internal/log` di sisi LINE (batch 3.2): konsol menarik WARNING/ERROR line ini.

Dirakit lewat `buat_router()` dengan dependensi disuntik, seperti
`routes/internal_outbox.py`: `routes/internal.py` menarik torch, dan lane ini harus
teruji di CI. Rute `def` biasa: FastAPI menjalankannya di threadpool, jadi SQLite
tidak menahan loop yang melayani `/internal/status` tiap detik.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.config import Settings
from ..domain.log_line import BATAS_HALAMAN, BATAS_HALAMAN_MAKS, PANJANG_GENERASI_MAKS
from ..repositories.log_line_repository import LogLineStore
from .penjaga_rahasia import penjaga_internal


def buat_router(
    *, settings: Callable[[], Settings], store: Callable[[], LogLineStore | None]
) -> APIRouter:
    """Router `/internal/log` untuk satu proses line, di balik `INTERNAL_SECRET`."""
    router = APIRouter(
        prefix="/internal",
        tags=["internal"],
        dependencies=[Depends(penjaga_internal(settings))],
    )

    @router.get("/log")
    def log_line(
        setelah: Annotated[int, Query(ge=0)] = 0,
        generasi: Annotated[str, Query(max_length=PANJANG_GENERASI_MAKS)] = "",
        batas: Annotated[int, Query(ge=1, le=BATAS_HALAMAN_MAKS)] = BATAS_HALAMAN,
    ) -> dict[str, Any]:
        """Satu halaman sesudah kursor konsol. Generasi lain = mulai dari awal berkas ini."""
        log = store()
        if log is None:
            raise HTTPException(status_code=503, detail="log_line_mati")
        return log.ambil(setelah=setelah, generasi=generasi, batas=batas)

    return router
