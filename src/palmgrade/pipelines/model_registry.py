from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
from ultralytics import YOLO  # type: ignore

from ..core.config import Settings

logging.getLogger("ultralytics").setLevel(logging.WARNING)


class ModelRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger = logging.getLogger(__name__)
        logger.info("Using device: %s", self.device)

        if not settings.ripeness_model_path.exists():
            raise FileNotFoundError(f"Model tidak ditemukan: {settings.ripeness_model_path}")

        self.model: YOLO = YOLO(str(settings.ripeness_model_path))

        if self.device == "cuda":
            self.model.to(self.device).half()

        # Warm-up: dummy inference pakai resolusi kamera asli agar tidak ada jitter di frame pertama
        dummy = np.zeros((settings.camera_height, settings.camera_width, 3), dtype=np.uint8)
        self.model.predict(dummy, verbose=False)
        logger.info("Model warm-up complete")

    @property
    def release_dir(self) -> Path:
        return self.settings.models_release_dir

    @property
    def experiments_dir(self) -> Path:
        return self.settings.models_experiments_dir
