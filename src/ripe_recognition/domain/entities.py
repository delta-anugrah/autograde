from __future__ import annotations

from dataclasses import dataclass

from .value_objects import BoundingBox, CaptureType, InspectionStatus, TrunkBox


@dataclass
class InspectionResult:
    id: str
    status: InspectionStatus
    prediction: str
    confidence: float
    timestamp: str
    image_url: str
    capture_type: CaptureType
    truck_id: str | None = None
    bounding_box: BoundingBox | None = None
    trunk_box: TrunkBox | None = None

    @property
    def title(self) -> str:
        suffix = "(Manual)" if self.capture_type == "manual" else ""
        return f"{self.status} Detected {suffix}".strip()

    @property
    def description(self) -> str:
        return (
            f"Prediction={self.prediction} "
            f"(conf={self.confidence:.2f}, truck_id={self.truck_id})"
        )
