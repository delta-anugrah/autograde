from dataclasses import dataclass
from typing import Any

from ..pipelines.realtime_inspection_pipeline import RealtimeInspectionPipeline


@dataclass
class InspectionService:
    pipeline: RealtimeInspectionPipeline

    def get_runtime_status(self) -> dict[str, Any]:
        return self.pipeline.get_status()

