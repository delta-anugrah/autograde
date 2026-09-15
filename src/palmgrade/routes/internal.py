from __future__ import annotations

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
)
from ..services.capture_service import CaptureService
from ..workers.runtime_state import RuntimeState


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
    # Kembalikan event dead-letter (status='failed') ke 'pending' agar
    # OutboxRetryWorker mencoba kirim lagi. Dipakai setelah API pulih dari
    # gangguan panjang. Aman diulang (idempotent kalau tidak ada failed).
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
