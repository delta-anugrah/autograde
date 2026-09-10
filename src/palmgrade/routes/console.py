"""Route konsol operator. Dipasang HANYA oleh `console_main.py`.

Sengaja route → service → repository tanpa controller pass-through: lapisan
controller di repo ini isinya cuma meneruskan argumen, dan konsol tidak punya
logika yang butuh tempat menganggur di antaranya.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from ..core.config import Settings
from ..integrations.notifications.line_client import LineClient, LineUnavailable
from ..repositories.console_repository import ConsoleStore
from ..services.console_service import ConsoleService

_CONSOLE_HTML = Path(__file__).resolve().parents[1] / "static" / "console.html"


@lru_cache
def get_console_service() -> ConsoleService:
    """Composition root konsol. Satu-satunya tempat yang merakit ketiganya."""
    settings = Settings()
    return ConsoleService(settings, ConsoleStore(settings.console_db_path), LineClient(settings))


Service = Annotated[ConsoleService, Depends(get_console_service)]

# ── layar operator + API-nya (localhost, tanpa auth) ────────────────────
# Konsol berdiri di PC operator dan cuma dibuka lewat http://127.0.0.1:8000
# (§4: 127.0.0.1 origin tepercaya, 192.168.x.x TIDAK). Login operator = §6.5,
# bukan bagian Fase 2.
router = APIRouter(tags=["console"])


@router.get("/console", include_in_schema=False)
async def console_page() -> FileResponse:
    return FileResponse(_CONSOLE_HTML, media_type="text/html")


@router.get("/api/console/state")
async def console_state(service: Service) -> dict:
    return service.state()


@router.get("/api/console/history")
async def console_history(
    service: Service,
    tanggal_kerja: str | None = None,
    line_code: str | None = None,
    truck_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    tanggal = tanggal_kerja or service.today()
    return {
        "tanggal_kerja": tanggal,
        "items": service.history(
            tanggal, line_code=line_code, truck_id=truck_id, limit=limit, offset=offset
        ),
    }


@router.get("/api/console/trucks")
async def console_trucks(service: Service) -> dict:
    return {"items": service.trucks()}


@router.post("/api/console/lines/{line_code}/assign-truck")
async def assign_truck(
    line_code: str, service: Service, truck_id: Annotated[str, Body(embed=True)]
) -> dict:
    try:
        return await service.assign_truck(line_code, truck_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LineUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/console/lines/{line_code}/manual-reject")
async def manual_reject(
    line_code: str, service: Service, requested_by: Annotated[str, Body(embed=True)] = "operator"
) -> dict:
    try:
        return await service.manual_reject(line_code, requested_by)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LineUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ── penerima event dari tiga line (kontrak beku §5) ─────────────────────
# Bentuk URL & header-nya WAJIB identik dengan palmgrade-api, karena yang
# mengirim adalah OutboxRetryWorker line yang tidak diubah sama sekali.
ingest_router = APIRouter(tags=["ingest"])


@ingest_router.post("/internal/vision/events", status_code=201)
async def ingest_event(
    service: Service,
    payload: Annotated[dict, Body()],
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict:
    if x_webhook_secret != service.settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        tanggal_kerja = service.ingest(payload)
    except ValueError as exc:
        # 400 → outbox line menahan & menandai gagal. Sengaja tidak 200:
        # event cacat harus kelihatan, bukan hilang diam-diam.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "tanggal_kerja": tanggal_kerja}
