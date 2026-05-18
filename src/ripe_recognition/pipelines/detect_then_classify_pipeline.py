from dataclasses import dataclass
from typing import Any

from .model_registry import ModelRegistry


@dataclass
class DetectThenClassifyPipeline:
    model_registry: ModelRegistry

    def run(self, source: Any) -> dict[str, Any]:
        return {
            "message": "Detect-then-classify pipeline skeleton is ready.",
            "source_provided": source is not None,
        }

