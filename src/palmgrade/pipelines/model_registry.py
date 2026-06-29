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

        self.backend = "pytorch"
        self.model: YOLO = self._load_model(settings, logger)

        # Warm-up: dummy inference pakai resolusi kamera asli agar tidak ada jitter di frame pertama
        dummy = np.zeros((settings.camera_height, settings.camera_width, 3), dtype=np.uint8)
        self.model.predict(dummy, verbose=False)
        logger.info("Model warm-up complete (backend=%s)", self.backend)

    def _load_model(self, settings: Settings, logger: logging.Logger) -> YOLO:
        # Prefer TensorRT engine kalau sudah ada untuk GPU ini (lebih cepat, akurasi sama).
        if self.device == "cuda":
            try:
                cc_major, cc_minor = torch.cuda.get_device_capability(0)
                engine_path = settings.engine_path_for_gpu(f"{cc_major}{cc_minor}")
            except Exception:
                engine_path = None

            if engine_path is not None and engine_path.exists():
                try:
                    model = YOLO(str(engine_path), task="detect")
                    self.backend = "tensorrt"
                    logger.info("Loaded TensorRT engine: %s", engine_path)
                    return model
                except Exception as exc:
                    logger.warning(
                        "TensorRT engine gagal di-load (%s) — fallback ke .pt. "
                        "Rebuild via `make build-engine`.", exc,
                    )
            elif engine_path is not None:
                logger.info(
                    "Belum ada TensorRT engine untuk GPU ini (%s) — pakai .pt. "
                    "Jalankan `make build-engine` untuk speedup.", engine_path,
                )

        if not settings.ripeness_model_path.exists():
            raise FileNotFoundError(f"Model tidak ditemukan: {settings.ripeness_model_path}")

        model = YOLO(str(settings.ripeness_model_path))
        if self.device == "cuda":
            model.to(self.device).half()
        self.backend = "pytorch"
        return model

    @property
    def release_dir(self) -> Path:
        return self.settings.models_release_dir

    @property
    def experiments_dir(self) -> Path:
        return self.settings.models_experiments_dir
