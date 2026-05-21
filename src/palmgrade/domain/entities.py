from __future__ import annotations

from dataclasses import dataclass, field

from .value_objects import BoundingBox, CaptureType


@dataclass
class InspectionResult:
    id: str
    ripeness_status: str           # "acc" | "rej"
    ripeness_confidence: float
    timestamp: str
    image_url: str
    capture_type: CaptureType
    machine_id: str = ""
    truck_id: str | None = None
    tp_status: str | None = None   # "TP" | None
    tp_confidence: float = 0.0
    bounding_box: BoundingBox | None = None

    @property
    def title(self) -> str:
        suffix = "(Manual)" if self.capture_type == "manual" else ""
        return f"{self.ripeness_status.upper()} Detected {suffix}".strip()

    @property
    def description(self) -> str:
        return (
            f"ripeness={self.ripeness_status} "
            f"(conf={self.ripeness_confidence:.2f}, truck_id={self.truck_id})"
        )
