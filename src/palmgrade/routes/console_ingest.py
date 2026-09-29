"""Machine lane of the console: the three lines and the scale program.

No session here: machines authenticate with `x-webhook-secret`. Split out of
`routes/console.py` (batch 1, 2026-09-28); URL and header shape still MUST match
palmgrade-api, the sender is the line's unchanged OutboxRetryWorker.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Header, HTTPException

from ..domain.rahasia import rahasia_cocok
from .console_deps import Service

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
    if not rahasia_cocok(x_webhook_secret, service.settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        work_date = service.ingest(payload)
    except ValueError as exc:
        # 400 → the line's outbox keeps it and retries; rows are never
        # dead-lettered, so `outbox_failed` stays 0 on a line on this image (a
        # line on an older image may still report more than 0). Not 200 on
        # purpose: a malformed event must be held, not vanish.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "work_date": work_date}


@ingest_router.get("/internal/setelan")
async def setelan_untuk_line(
    service: Service,
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict:
    """Setelan grading yang berlaku, untuk diambil LINE saat dia start.

    Lane mesin (`x-webhook-secret`), bukan lane operator: line tidak punya sesi.
    Ini yang membuat setelan bertahan saat container line dibuat ulang — override
    di `RuntimeState` hilang bersama prosesnya, jadi line menanyakannya lagi.
    Konsol tetap satu-satunya pemegang kebenaran; line cuma menyalin.
    """
    if not rahasia_cocok(x_webhook_secret, service.settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    return service.setelan_grading()


@ingest_router.get("/internal/penugasan")
async def penugasan_untuk_line(
    service: Service,
    machine_id: str,
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict:
    """Penugasan truk yang berlaku untuk satu line, diambil LINE saat dia start.

    Lane mesin (`x-webhook-secret`), bukan lane operator: line tidak punya sesi.
    Sepasang dengan `/internal/setelan` — keduanya memulihkan hal yang hidup di
    `RuntimeState` dan karena itu hilang saat container line dibuat ulang.

    `machine_id` wajib: konsol memegang penugasan tiga line, dan menjawab tanpa
    tahu siapa yang bertanya akan mengirimkan truk line lain — tonase mendarat di
    truk yang salah, tanpa satu pun pesan.
    """
    if not rahasia_cocok(x_webhook_secret, service.settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    return service.penugasan_untuk_mesin(machine_id)


@ingest_router.post("/internal/scale/weighing", status_code=201)
async def ingest_weighing(
    service: Service,
    payload: Annotated[dict, Body()],
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict:
    """Scale program payload (§3.5c). Same secret as the event lane.

    The real format is unknown (docs/PERTANYAAN-TERBUKA.md X1); what is frozen
    here is our shape — `plate_number`, `gross_kg`, `tare_kg`, `entered_at`,
    `exited_at`, optional `ref`. An adapter follows once the format lands.
    """
    if not rahasia_cocok(x_webhook_secret, service.settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        return await service.record_weighing(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
