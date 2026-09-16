from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
from ultralytics import YOLO

from ..core.config import Settings
from ..domain.grade_class import GRADE_CLASSES  # type: ignore
from ..domain.grade_class import grade_class_or_none as _grade_class_or_none

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
        _warn_on_unexpected_classes(model, logger)
        return model

    @property
    def release_dir(self) -> Path:
        return self.settings.models_release_dir

    @property
    def experiments_dir(self) -> Path:
        return self.settings.models_experiments_dir


def _warn_on_unexpected_classes(model, logger: logging.Logger) -> None:
    """Adukan saat startup kalau kelas model bukan keempat yang dikenal.

    Model yang salah pasang tidak pernah error: YOLO memuatnya dengan senang
    hati, `grade_class_of` menolak tiap label, dan tiap janjang dilewati. Yang
    terlihat di layar cuma angka yang tidak pernah naik — line yang "jalan" tapi
    tidak menghitung apa pun. Satu baris ERROR di startup jauh lebih murah
    daripada menemukannya sesudah satu shift.

    Sengaja peringatan, bukan `raise`: nama kelas itu metadata hasil latih, dan
    mematikan line di pabrik gara-gara ejaan bukan keputusan yang boleh diambil
    kode ini sendiri.
    """
    try:
        names = set(getattr(model, "names", {}).values())
    except Exception:
        return
    if not names:
        return
    unknown = {n for n in names if _grade_class_or_none(n) is None}
    missing = {c for c in GRADE_CLASSES if c not in {_grade_class_or_none(n) for n in names}}
    if unknown or missing:
        logger.error(
            "Kelas model tidak seperti yang diharapkan. Ada: %s. "
            "Tidak dikenal: %s. Hilang: %s. Yang diharapkan: %s. "
            "Cek MODEL_FILE menunjuk ke model yang benar — kelas yang tidak "
            "dikenal DILEWATI, jadi line bisa terlihat jalan tanpa menghitung.",
            sorted(names), sorted(unknown) or "-", sorted(missing) or "-",
            list(GRADE_CLASSES),
        )
    else:
        logger.info("Kelas model terverifikasi: %s", sorted(names))
