from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from ..schemas.internal_schema import (
    AssignmentSyncRequest,
    AssignmentSyncResponse,
    ManualRejectCommandRequest,
    ManualRejectCommandResponse,
)
from ..services.capture_service import CaptureService
from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)


async def sync_assignment(request: AssignmentSyncRequest, state: RuntimeState) -> AssignmentSyncResponse:
    state.current_truck_id = request.truck_id
    state.current_assignment_id = request.assignment_id
    logger.info(
        "Assignment synced: machine=%s truck=%s assignment=%s",
        request.machine_id, request.truck_id, request.assignment_id,
    )
    return AssignmentSyncResponse(
        accepted=True,
        machine_id=request.machine_id,
        truck_id=request.truck_id,
        assignment_id=request.assignment_id,
    )


async def manual_reject_command(
    request: ManualRejectCommandRequest,
    service: CaptureService,
) -> ManualRejectCommandResponse:
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, service.capture_manual_reject)
        logger.info("Manual reject executed: machine=%s assignment=%s", request.machine_id, request.assignment_id)
        return ManualRejectCommandResponse(accepted=True, message="capture_reject_requested")
    except RuntimeError as exc:
        logger.warning("Manual reject failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
