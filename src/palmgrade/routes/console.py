"""Operator console routes. Mounted ONLY by `console_main.py`.

Deliberately route → service → repository with no pass-through controller: the
controller layer in this repo only forwards arguments, and the console has no
logic that needs an idle stop in between.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from ..core.config import Settings
from ..domain.operator_error import OperatorError
from ..integrations.erp.outbox_store import ErpOutboxStore
from ..integrations.notifications.line_client import LineClient, LineUnavailable
from ..repositories.console_repository import ConsoleStore
from ..services.console_service import ConsoleService
from ..services.erp_queue import ErpQueue

_CONSOLE_HTML = Path(__file__).resolve().parents[1] / "static" / "console.html"


@lru_cache
def get_console_service() -> ConsoleService:
    """Console composition root. The only place these are wired."""
    settings = Settings()
    store = ConsoleStore(settings.console_db_path)
    queue = ErpQueue(
        store, ErpOutboxStore(settings.erp_outbox_db_path), site=settings.erp_company
    )
    return ConsoleService(settings, store, LineClient(settings), erp_queue=queue)


Service = Annotated[ConsoleService, Depends(get_console_service)]


def _operator_error(status_code: int, exc: Exception) -> HTTPException:
    """Operator routes answer with a code the screen words in its own language.

    Machine lanes (events, scale program) keep a plain-text detail — see below.
    """
    detail = exc.as_detail() if isinstance(exc, OperatorError) else str(exc)
    return HTTPException(status_code=status_code, detail=detail)

# ── operator screen + its API (localhost, no auth) ──────────────────────
# The console sits on the operator PC and is only opened via
# http://127.0.0.1:8000 (§4: 127.0.0.1 is a trusted origin, 192.168.x.x is
# NOT). Operator login is §6.5, not part of phase 2.
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


@router.post("/api/console/trucks", status_code=201)
async def daftar_truk_manual(service: Service, payload: Annotated[dict, Body()]) -> dict:
    """Borrowed or unregistered truck, typed by the operator (not from cloud master)."""
    try:
        return service.daftar_truk_manual(
            str(payload.get("plate_number") or ""),
            supplier_id=payload.get("supplier_id"),
            capacity=payload.get("capacity"),
        )
    except ValueError as exc:
        raise _operator_error(400, exc) from exc


@router.get("/api/console/weighings")
async def console_weighings(
    service: Service,
    tanggal_kerja: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    tanggal = tanggal_kerja or service.today()
    return {"tanggal_kerja": tanggal, "items": service.weighings(tanggal, limit=limit)}


@router.get("/api/console/recap")
async def console_recap(service: Service, tanggal_kerja: str | None = None) -> dict:
    """What the supplier is handed: bunches and neto per truck for one day."""
    tanggal = tanggal_kerja or service.today()
    return {"tanggal_kerja": tanggal, "items": service.rekap(tanggal)}


@router.post("/api/console/weighings", status_code=201)
async def catat_timbangan_manual(service: Service, payload: Annotated[dict, Body()]) -> dict:
    """Operator types bruto/tara by hand; the payload shape is identical to the
    scale program's — only without the secret, since the console is opened from
    127.0.0.1 only (§4). This lane keeps weighing tickets flowing while the
    scale program's format is unknown (docs/PERTANYAAN-TERBUKA.md X1).
    """
    try:
        return service.catat_timbangan(payload)
    except ValueError as exc:
        raise _operator_error(400, exc) from exc


@router.post("/api/console/lines/{line_code}/assign-truck")
async def assign_truck(
    line_code: str, service: Service, truck_id: Annotated[str, Body(embed=True)]
) -> dict:
    try:
        return await service.assign_truck(line_code, truck_id)
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


@router.post("/api/console/lines/{line_code}/release-truck")
async def release_truck(line_code: str, service: Service) -> dict:
    """Truck leaves. The line is told too — see `ConsoleService.lepas_truk`."""
    try:
        return await service.lepas_truk(line_code)
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


@router.post("/api/console/lines/{line_code}/manual-reject")
async def manual_reject(
    line_code: str, service: Service, requested_by: Annotated[str, Body(embed=True)] = "operator"
) -> dict:
    try:
        return await service.manual_reject(line_code, requested_by)
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


# ── event receiver for the three lines (frozen contract §5) ─────────────
# URL and header shape MUST match palmgrade-api: the sender is the line's
# OutboxRetryWorker, which is not modified at all.
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
        # 400 → the line's outbox holds it and marks it failed. Not 200 on
        # purpose: a malformed event must be visible, not vanish.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "tanggal_kerja": tanggal_kerja}


@ingest_router.post("/internal/scale/weighing", status_code=201)
async def ingest_weighing(
    service: Service,
    payload: Annotated[dict, Body()],
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict:
    """Scale program payload (§3.5c). Same secret as the event lane.

    The real format is unknown (docs/PERTANYAAN-TERBUKA.md X1); what is frozen
    here is our shape — `plate_number`, `bruto_kg`, `tara_kg`, `waktu_masuk`,
    `waktu_keluar`, optional `ref`. An adapter follows once the format lands.
    """
    if x_webhook_secret != service.settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        return service.catat_timbangan(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
