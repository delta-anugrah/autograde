"""`GET /health` line: ringan, jujur soal AI mati dan frame berhenti, dan teruji di CI.

Dirakit lewat `buat_router_health()` dengan pembuat `HealthService` disuntik,
BUKAN lewat `core.dependencies` (yang menarik torch; pola `internal_bahaya.py`):
jawaban ini dibaca healthcheck Docker DAN gerbang `autograde.sh`, jadi kode
statusnya harus teruji di CI.

503 untuk AI mati DAN frame berhenti (kamera tersambung tapi tidak mengirim gambar),
satu aturan di `domain/kesehatan_ai.kode_http_health`; kamera putus, lisensi, dan sumber
selesai tetap 200. Badan jawabannya tetap dikirim di 503: manusia yang membuka
`curl :8001/health` langsung membaca keadaannya (`ai.keadaan`, `ai.kode`).
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..domain.kesehatan_ai import kode_http_health
from ..schemas.common_schema import HealthRinganSchema
from ..services.health_service import HealthService


def buat_router_health(service: Callable[[], HealthService]) -> APIRouter:
    router = APIRouter(tags=["health"])

    # `service()` dipanggil di dalam, bukan lewat `Depends(service)`: dengan
    # `from __future__ import annotations` FastAPI mencari nama di anotasi pada
    # globals modul, dan `service` hidup di closure ini (jawabannya jadi 422).
    @router.get(
        "/health",
        response_model=HealthRinganSchema,
        responses={503: {"model": HealthRinganSchema, "description": "Line ini tidak menyortir: AI mati atau frame berhenti (lihat ai.kode)"}},
    )
    async def healthcheck() -> JSONResponse:
        isi = HealthRinganSchema.model_validate(service().get_health())
        return JSONResponse(status_code=kode_http_health(isi.ai), content=isi.model_dump())

    return router
