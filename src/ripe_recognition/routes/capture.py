from typing import Annotated

from fastapi import APIRouter, Depends

from ..controllers.capture_controller import capture_reject
from ..core.dependencies import get_capture_service
from ..schemas.capture_schema import CaptureRejectResponse
from ..services.capture_service import CaptureService

router = APIRouter(prefix="/api", tags=["capture"])


@router.post("/capture_reject", response_model=CaptureRejectResponse)
async def capture_reject_route(
    service: Annotated[CaptureService, Depends(get_capture_service)],
) -> CaptureRejectResponse:
    return await capture_reject(service)

