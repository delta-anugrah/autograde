from __future__ import annotations

import asyncio

from fastapi import HTTPException

from ..schemas.capture_schema import CaptureRejectResponse
from ..services.capture_service import CaptureService


async def capture_reject(service: CaptureService) -> CaptureRejectResponse:
    try:
        loop = asyncio.get_event_loop()
        payload = await loop.run_in_executor(None, service.capture_manual_reject)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return CaptureRejectResponse.model_validate(payload)
