from fastapi import HTTPException

from ..schemas.capture_schema import CaptureRejectResponse
from ..services.capture_service import CaptureService


async def capture_reject(service: CaptureService) -> CaptureRejectResponse:
    try:
        payload = service.capture_manual_reject()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return CaptureRejectResponse.model_validate(payload)
