from dataclasses import dataclass
from typing import Any

from .model_registry import ModelRegistry


@dataclass
class TrunkDetectionPipeline:
    model_registry: ModelRegistry

    def run(self, frame: Any) -> dict[str, Any]:
        return {
            "message": "Trunk detection pipeline skeleton is ready.",
            "frame_received": frame is not None,
        }

