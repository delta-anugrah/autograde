from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from ..controllers.internal_controller import (
    line_status,
    manual_reject_command,
    piston_command,
    plc_coil_command,
    plc_state,
    sync_assignment,
)
from ..core.dependencies import (
    get_capture_service,
    get_outbox_store,
    get_runtime_state,
    get_settings,
)
from ..core.config import Settings
from ..domain.setelan_grading import bersihkan_setelan
from ..integrations.outbox.outbox_store import OutboxStore
from ..schemas.internal_schema import (
    AssignmentSyncRequest,
    AssignmentSyncResponse,
    LineStatusResponse,
    ManualRejectCommandRequest,
    ManualRejectCommandResponse,
    OutboxRequeueResponse,
    PistonCommandRequest,
    PlcCoilCommandRequest,
    PlcCoilCommandResponse,
    PlcStateResponse,
    SetelanGradingRequest,
    SetelanGradingResponse,
)
from ..services.capture_service import CaptureService
from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)


async def _verify_internal_secret(
    x_internal_secret: Annotated[str | None, Header()] = None,
) -> None:
    settings = get_settings()
    if x_internal_secret != settings.internal_secret:
        raise HTTPException(status_code=401, detail="Invalid internal secret")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(_verify_internal_secret)],
)


@router.post("/assignment", response_model=AssignmentSyncResponse)
async def assignment_sync(
    request: AssignmentSyncRequest,
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
) -> AssignmentSyncResponse:
    return await sync_assignment(request, state)


@router.post("/setelan", response_model=SetelanGradingResponse)
async def setelan_grading(
    request: SetelanGradingRequest,
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SetelanGradingResponse:
    """Timpa CONF_THRESHOLD/MINIMUM_SIZE line ini tanpa restart.

    Disimpan di `RuntimeState`, bukan di `Settings` (yang `frozen=True` dengan
    sengaja). Hilang kalau container dibuat ulang — itu disengaja: konsol yang
    memegang nilai sebenarnya dan mengirimnya lagi saat line kembali online,
    jadi tidak ada dua sumber kebenaran yang bisa berbeda diam-diam.
    """
    bersih = bersihkan_setelan(request.model_dump())
    state.conf_threshold_override = bersih["conf_threshold"]
    state.minimum_size_override = bersih["minimum_size"]
    state.garis_capture_override = bersih["garis_capture"]
    state.sumbu_garis_override = bersih["sumbu_garis"]
    logger.warning(
        "Setelan grading diubah dari konsol: conf=%s minimum_size=%s garis=%s sumbu=%s "
        "(sebelumnya env conf=%s size=%s garis=%s sumbu=%s)",
        bersih["conf_threshold"], bersih["minimum_size"], bersih["garis_capture"],
        bersih["sumbu_garis"],
        settings.conf_threshold, settings.minimum_size, settings.garis_capture,
        settings.sumbu_garis,
    )
    return SetelanGradingResponse(**bersih, sumber="konsol")


@router.get("/setelan", response_model=SetelanGradingResponse)
async def setelan_grading_aktif(
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SetelanGradingResponse:
    """Yang BENAR-BENAR dipakai line ini sekarang, bukan yang ada di `.env`."""
    ditimpa = state.conf_threshold_override is not None
    return SetelanGradingResponse(
        conf_threshold=state.conf_threshold_override
        if ditimpa else settings.conf_threshold,
        minimum_size=state.minimum_size_override
        if state.minimum_size_override is not None else settings.minimum_size,
        garis_capture=state.garis_capture_override
        if state.garis_capture_override is not None else settings.garis_capture,
        sumbu_garis=state.sumbu_garis_override
        if state.sumbu_garis_override is not None else settings.sumbu_garis,
        sumber="konsol" if ditimpa else "env",
    )


@router.post("/manual-reject", response_model=ManualRejectCommandResponse)
async def manual_reject(
    request: ManualRejectCommandRequest,
    service: Annotated[CaptureService, Depends(get_capture_service)],
) -> ManualRejectCommandResponse:
    return await manual_reject_command(request, service)


@router.post("/outbox/requeue", response_model=OutboxRequeueResponse)
async def outbox_requeue(
    outbox: Annotated[OutboxStore, Depends(get_outbox_store)],
) -> OutboxRequeueResponse:
    # Move dead-letter events (status='failed') back to 'pending' so
    # OutboxRetryWorker tries sending them again. Used after the API recovers
    # from a long outage. Safe to repeat (idempotent when nothing has failed).
    return OutboxRequeueResponse(requeued=outbox.requeue_failed())


@router.post("/piston", response_model=LineStatusResponse)
async def piston(
    request: PistonCommandRequest,
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
) -> LineStatusResponse:
    return await piston_command(request, state)


@router.get("/status", response_model=LineStatusResponse)
async def line_status_endpoint(
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
) -> LineStatusResponse:
    return await line_status(state)


@router.get("/plc", response_model=PlcStateResponse)
async def plc_state_endpoint() -> PlcStateResponse:
    return await plc_state()


@router.post("/plc/coil", response_model=PlcCoilCommandResponse)
async def plc_coil(
    request: PlcCoilCommandRequest,
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
) -> PlcCoilCommandResponse:
    return await plc_coil_command(request, state)
