from pydantic import BaseModel


class CaptureRejectResponse(BaseModel):
    id: str
    ripeness_status: str
    ripeness_confidence: float
    tp_status: str | None = None
    tp_confidence: float = 0
    title: str
    description: str
    timestamp: str
    image_url: str | None = None
    capture_type: str
    truck_id: str | None = None
    bounding_box: dict | None = None
