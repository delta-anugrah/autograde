from fastapi.responses import StreamingResponse

from ..services.streaming_service import StreamingService


async def get_video_feed(service: StreamingService) -> StreamingResponse:
    return StreamingResponse(
        service.generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "close",
        },
    )
