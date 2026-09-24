from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
from ultralytics import YOLO

from ..core.config import Settings
from ..domain.grade_class import GRADE_CLASSES, periksa_kelas

logging.getLogger("ultralytics").setLevel(logging.WARNING)


class ModelRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger = logging.getLogger(__name__)
        logger.info("Using device: %s", self.device)

        self.backend = "pytorch"
        # Compute capability GPU ini ("86" = RTX 3060). Menentukan engine mana
        # yang dipakai, dan dilaporkan supaya konsol tahu engine mana yang
        # benar-benar berguna bagi line ini. None = CPU / tidak terbaca.
        self.gpu_sm: str | None = None
        if self.device == "cuda":
            try:
                cc_major, cc_minor = torch.cuda.get_device_capability(0)
                self.gpu_sm = f"{cc_major}{cc_minor}"
            except Exception:
                self.gpu_sm = None
        self.model: YOLO = self._load_model(settings, logger)

        # Warm-up: dummy inference pakai resolusi kamera asli agar tidak ada jitter di frame pertama
        dummy = np.zeros((settings.camera_height, settings.camera_width, 3), dtype=np.uint8)
        self.model.predict(dummy, verbose=False)
        logger.info("Model warm-up complete (backend=%s)", self.backend)

        # Diperiksa SESUDAH warm-up, untuk kedua backend. Dulu cuma jalur `.pt`
        # yang memeriksa, jadi line ber-engine TensorRT — setiap PC pabrik —
        # memuat engine hasil model lama tanpa satu pun ERROR. Nama kelas
        # engine datang dari metadata yang dibaca Ultralytics saat warm-up.
        self.kelas = _nama_kelas(self.model)
        asing, hilang = periksa_kelas(self.kelas)
        self.kelas_cocok = bool(self.kelas) and not asing and not hilang
        _warn_on_unexpected_classes(self.kelas, logger)

    def ringkasan(self) -> dict:
        """Model yang BENAR-BENAR dimuat, untuk `/health/detail` dan layar Model Deteksi."""
        return {
            "model_file": self.settings.model_file,
            "model_backend": self.backend,
            "model_kelas": list(self.kelas),
            # Alarm yang layar tampilkan merah. Log ERROR di atas cuma terbaca
            # lewat AnyDesk; ini yang terbaca dari konsol.
            "model_kelas_cocok": self.kelas_cocok,
            "gpu_sm": self.gpu_sm,
        }

    def _load_model(self, settings: Settings, logger: logging.Logger) -> YOLO:
        # Prefer TensorRT engine kalau sudah ada untuk GPU ini (lebih cepat, akurasi sama).
        if self.device == "cuda":
            engine_path = settings.engine_path_for_gpu(self.gpu_sm) if self.gpu_sm else None

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


def _warn_on_unexpected_classes(names: list[str], logger: logging.Logger) -> None:
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
    if not names:
        return
    unknown, missing = periksa_kelas(names)
    if unknown or missing:
        logger.error(
            "Kelas model tidak seperti yang diharapkan. Ada: %s. "
            "Tidak dikenal: %s. Hilang: %s. Yang diharapkan: %s. "
            "Cek model line ini (layar Support > Model Deteksi, atau MODEL_FILE) — "
            "kelas yang tidak dikenal DILEWATI, jadi line bisa terlihat jalan tanpa menghitung.",
            sorted(names), unknown or "-", missing or "-",
            list(GRADE_CLASSES),
        )
    else:
        logger.info("Kelas model terverifikasi: %s", sorted(names))


def _nama_kelas(model) -> list[str]:
    """Nama kelas model, urut indeks. Kosong kalau tidak terbaca."""
    try:
        names = getattr(model, "names", None) or {}
    except Exception:
        return []
    if isinstance(names, dict):
        return [str(names[k]) for k in sorted(names)]
    return [str(n) for n in names]
