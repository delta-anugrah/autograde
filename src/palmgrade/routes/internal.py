from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from ..controllers.internal_controller import manual_reject_command, sync_assignment
from ..core.dependencies import get_capture_service, get_runtime_state, get_settings
from ..schemas.internal_schema import (
    AssignmentSyncRequest,
    AssignmentSyncResponse,
    ManualRejectCommandRequest,
    ManualRejectCommandResponse,
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
