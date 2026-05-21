from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..controllers.streaming_controller import get_video_feed
from ..core.dependencies import get_streaming_service
from ..services.streaming_service import StreamingService

router = APIRouter(prefix="/api", tags=["streaming"])


@router.get("/video_feed")
async def video_feed(
    service: Annotated[StreamingService, Depends(get_streaming_service)],
) -> StreamingResponse:
    return await get_video_feed(service)
