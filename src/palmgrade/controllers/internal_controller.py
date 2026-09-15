from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from ..schemas.internal_schema import (
    AssignmentSyncRequest,
    AssignmentSyncResponse,
    LineStatusResponse,
    ManualRejectCommandRequest,
    ManualRejectCommandResponse,
    PistonCommandRequest,
    PlcCoilCommandRequest,
    PlcCoilCommandResponse,
    PlcStateResponse,
)
from ..services.capture_service import CaptureService
from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)


async def sync_assignment(request: AssignmentSyncRequest, state: RuntimeState) -> AssignmentSyncResponse:
    state.current_truck_id = request.truck_id
    state.current_assignment_id = request.assignment_id
    state.current_ffb_source = request.ffb_source
    logger.info(
        "Assignment synced: machine=%s truck=%s assignment=%s ffb_source=%s",
        request.machine_id, request.truck_id, request.assignment_id, request.ffb_source,
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


async def piston_command(request: PistonCommandRequest, state: RuntimeState) -> LineStatusResponse:
    from ..plc import request_piston

    if not request_piston(request.open):
        # 409, bukan 500: ini konfigurasi yang memang belum ada, bukan kerusakan.
        raise HTTPException(status_code=409, detail="piston_manual_tidak_aktif")
    logger.info(
        "Piston %s diminta: machine=%s oleh=%s pada=%s",
        "buka" if request.open else "tutup",
        request.machine_id, request.requested_by, request.requested_at,
    )
    return await line_status(state)


async def plc_state() -> PlcStateResponse:
    """Read-only: DI snapshot + which coils this line allows hand-firing.

    Never touches a coil — support can open the test screen at any time.
    `enabled=False` (PLC_ENABLED=false, the normal dev/cloud state) means
    the screen should say so, not error.
    """
    from ..core.dependencies import get_settings
    from ..plc import diagnostics, testable_coils

    snapshot = diagnostics()
    if snapshot is None:
        return PlcStateResponse(enabled=False)
    return PlcStateResponse(
        enabled=True,
        inputs=snapshot["inputs"],
        testable_coils=sorted(testable_coils(get_settings())),
    )


async def plc_coil_command(request: PlcCoilCommandRequest, state: RuntimeState) -> PlcCoilCommandResponse:
    """Fire one PLC coil for a commissioning wiring test (console dev screen only).

    Guarded here, not in the console: this process owns `state` and the real
    PLC connection, so this is the only place the check can't be bypassed by
    a stale read. Refused while a truck is being processed — a piston moving
    under a passing bunch is dangerous, not just untidy.
    """
    from ..core.dependencies import get_settings
    from ..plc import picu_coil, testable_coils

    if request.coil not in testable_coils(get_settings()):
        raise HTTPException(status_code=422, detail="coil_tidak_dikenal")
    if state.current_assignment_id is not None:
        raise HTTPException(status_code=409, detail="line_sedang_memproses_truk")
    fired = picu_coil(request.coil)
    # Container stdout only — the record that matters (`log_kejadian`, read by
    # the support screen) is written by the console, the only process with a
    # LogStore and the signed-in operator's identity.
    logger.warning(
        "UJI PLC: coil %s dipicu oleh %s (machine=%s, fired=%s)",
        request.coil, request.requested_by, request.machine_id, fired,
    )
    return PlcCoilCommandResponse(fired=fired, coil=request.coil)


async def line_status(state: RuntimeState) -> LineStatusResponse:
    from ..core.dependencies import get_settings
    from ..plc import piston_state

    return LineStatusResponse(
        machine_id=get_settings().machine_id,
        truck_id=state.current_truck_id,
        ffb_source=state.current_ffb_source,
        piston=piston_state(),
    )
