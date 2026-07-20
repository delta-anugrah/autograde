from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Nilai default WEBHOOK_SECRET yang ikut ke-commit di repo (dan dipakai sebagai
# fallback di docker-compose). Aman untuk dev, TAPI di production wajib diganti —
# lihat Settings.validate_for_runtime(). Dikonstanta di satu tempat supaya tidak
# tersebar sebagai magic string.
_DEFAULT_WEBHOOK_SECRET = "supersecret123"


@dataclass(frozen=True)
class Settings:
    app_name: str = "Ripe Recognition API"
    environment: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    host: str = field(default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("APP_PORT", os.getenv("RUNNING_PORT", "8000"))))
    frontend_url: str = field(default_factory=lambda: os.getenv("FRONTEND_URL", "*"))
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[3])

    # Webhook
    enable_webhook: bool = field(default_factory=lambda: _as_bool(os.getenv("ENABLE_WEBHOOK"), True))
    backend_url: str = field(default_factory=lambda: os.getenv("BACKEND_URL", "http://localhost:2500"))
    backend_api_ver: str = field(default_factory=lambda: os.getenv("BACKEND_API_VER", "/api/v1"))
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", _DEFAULT_WEBHOOK_SECRET))
    internal_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", _DEFAULT_WEBHOOK_SECRET))

    # Camera
    camera_type: str = field(default_factory=lambda: os.getenv("CAMERA_TYPE", "hikrobot"))
    camera_device_index: int = field(default_factory=lambda: int(os.getenv("CAMERA_DEVICE_INDEX", "0")))
    # Serial kamera Hikrobot (mis. "DA9069810"). Kalau diisi, pemilihan kamera
    # by-serial (stabil) menggantikan device_index — cegah rebutan antar line.
    # Kosong → fallback ke device_index (dev/webcam).
    camera_serial: str | None = field(
        default_factory=lambda: (os.getenv("CAMERA_SERIAL", "").strip() or None)
    )
    # File `.mfs` (MVS Feature Save) yang di-load ke kamera Hikrobot saat connect
    # (framerate/exposure/gain/dll). Kosong → skip, pakai setting firmware.
    # Non-fatal: gagal load → warning, kamera tetap grabbing.
    camera_feature_file: str | None = field(
        default_factory=lambda: (os.getenv("CAMERA_FEATURE_FILE", "").strip() or None)
    )
    camera_video_path: str = field(default_factory=lambda: os.getenv("CAMERA_VIDEO_PATH", ""))
    camera_width: int = field(default_factory=lambda: int(os.getenv("CAMERA_WIDTH", "320")))
    camera_height: int = field(default_factory=lambda: int(os.getenv("CAMERA_HEIGHT", "240")))
    camera_fps: int = field(default_factory=lambda: int(os.getenv("CAMERA_FPS", "30")))
    camera_photo_path: str = field(default_factory=lambda: os.getenv("CAMERA_PHOTO_PATH", ""))

    # Stream display resolution — only affects MJPEG stream, not saved captures
    stream_width: int = field(default_factory=lambda: int(os.getenv("STREAM_WIDTH", "1280")))
    stream_height: int = field(default_factory=lambda: int(os.getenv("STREAM_HEIGHT", "720")))
    stream_fps: int = field(default_factory=lambda: int(os.getenv("STREAM_FPS", "12")))

    # Line identification
    machine_id: str = field(default_factory=lambda: os.getenv("MACHINE_ID", ""))

    # License Guard
    lic_enabled: bool = field(default_factory=lambda: _as_bool(os.getenv("LIC_ENABLED"), False))
    lic_server_url: str = field(default_factory=lambda: os.getenv("LIC_SERVER_URL", ""))
    lic_api_key: str = field(default_factory=lambda: os.getenv("LIC_API_KEY", ""))
    lic_pubkey_pem: str = field(default_factory=lambda: os.getenv("LIC_PUBKEY_PEM", "").replace("\\n", "\n"))

    # Inference
    conf_threshold: float = field(default_factory=lambda: float(os.getenv("CONF_THRESHOLD", "0.75")))
    minimum_size: int = field(default_factory=lambda: int(os.getenv("MINIMUM_SIZE", "460000")))
    # Run YOLO every N frames — reduce CPU load on video-file testing (set to 1 for production)
    yolo_skip_frames: int = field(default_factory=lambda: int(os.getenv("YOLO_SKIP_FRAMES", "1")))

    # Detection zone — ROI rectangle (pixel coordinates, inclusive).
    # 0,0,0,0 = full frame (all objects eligible).
    # Set ROI_X1/Y1/X2/Y2 to restrict detection to a sub-region of the frame.
    roi_x1: int = field(default_factory=lambda: int(os.getenv("ROI_X1", "0")))
    roi_y1: int = field(default_factory=lambda: int(os.getenv("ROI_Y1", "0")))
    roi_x2: int = field(default_factory=lambda: int(os.getenv("ROI_X2", "0")))
    roi_y2: int = field(default_factory=lambda: int(os.getenv("ROI_Y2", "0")))

    # Display / annotation
    border_thickness: int = field(default_factory=lambda: int(os.getenv("BORDER_THICKNESS", "2")))
    font_scale: float = field(default_factory=lambda: float(os.getenv("FONT_SCALE", "0.7")))
    font_thickness: int = field(default_factory=lambda: int(os.getenv("FONT_THICKNESS", "2")))
    roi_scale: float = field(default_factory=lambda: float(os.getenv("ROI_SCALE", "0.7")))

    # Batch upload cloud (R2 + API cloud) — semua kredensial placeholder sampai
    # bucket/domain dibuat. R2_BUCKET kosong = batch worker no-op (saklar off).
    upload_minute: int = field(default_factory=lambda: int(os.getenv("UPLOAD_MINUTE", "0")))
    r2_account_id: str = field(default_factory=lambda: os.getenv("R2_ACCOUNT_ID", ""))
    r2_access_key_id: str = field(default_factory=lambda: os.getenv("R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = field(default_factory=lambda: os.getenv("R2_SECRET_ACCESS_KEY", ""))
    r2_bucket: str = field(default_factory=lambda: os.getenv("R2_BUCKET", ""))
    r2_public_url: str = field(default_factory=lambda: os.getenv("R2_PUBLIC_URL", "").rstrip("/"))
    # Target POST teks = API CLOUD. BACKEND_URL tetap menunjuk API LOKAL (webhook realtime).
    upload_api_url: str = field(default_factory=lambda: os.getenv("UPLOAD_API_URL", "").rstrip("/"))
    upload_api_secret: str = field(default_factory=lambda: os.getenv("UPLOAD_API_SECRET", ""))
    upload_max_items_per_tick: int = field(default_factory=lambda: int(os.getenv("UPLOAD_MAX_ITEMS_PER_TICK", "2000")))
    upload_retention_days: int = field(default_factory=lambda: int(os.getenv("UPLOAD_RETENTION_DAYS", "7")))

    # ------------------------------------------------------------------ validation

    def validate_for_runtime(self) -> None:
        """Fail-fast untuk salah konfigurasi yang berbahaya di production.

        WEBHOOK_SECRET mengamankan kedua arah antara vision <-> palmgrade-api.
        Kalau `.env` lupa diisi di PC prod, service dulu tetap jalan normal pakai
        default publik `supersecret123` (cuma warning) — siapa pun yang lihat repo
        bisa mengirim event palsu atau perintah internal. Di production kita tolak
        start; di development default tetap boleh (cuma warning) supaya alur
        dev/opencv lancar.
        """
        if self.environment == "production" and not self.r2_bucket:
            logger.warning(
                "R2_BUCKET kosong — batch upload ke cloud nonaktif (no-op). "
                "Isi R2_*/UPLOAD_API_* di .env untuk mengaktifkan."
            )
        if self.webhook_secret != _DEFAULT_WEBHOOK_SECRET:
            return
        if self.environment == "production":
            raise RuntimeError(
                "WEBHOOK_SECRET masih memakai nilai default publik di APP_ENV=production. "
                "Set WEBHOOK_SECRET ke nilai rahasia (harus sama dengan palmgrade-api) sebelum deploy."
            )
        logger.warning(
            "WEBHOOK_SECRET memakai nilai default — set sebelum deployment production."
        )

    # ------------------------------------------------------------------ paths

    @property
    def artifacts_dir(self) -> Path:
        return self.repo_root / "artifacts"

    @property
    def state_dir(self) -> Path:
        """Operational state (SQLite manifests) — di LUAR mount statis /captures."""
        return self.repo_root / "state"

    @property
    def captures_dir(self) -> Path:
        return self.artifacts_dir / "captures"

    @property
    def results_dir(self) -> Path:
        return self.artifacts_dir / "results"

    @property
    def errors_dir(self) -> Path:
        return self.artifacts_dir / "errors"

    @property
    def logs_dir(self) -> Path:
        return self.artifacts_dir / "logs"

    @property
    def models_release_dir(self) -> Path:
        return self.repo_root / "models" / "release"

    @property
    def models_experiments_dir(self) -> Path:
        return self.repo_root / "models" / "experiments"

    @property
    def ripeness_model_path(self) -> Path:
        model_file = os.getenv("MODEL_FILE", "best_3class_v2.pt")
        return self.models_release_dir / model_file

    @property
    def engines_dir(self) -> Path:
        # Writable (models/ is mounted read-only) — TensorRT engines cached here.
        return self.repo_root / "engines"

    def engine_path_for_gpu(self, compute_capability: str) -> Path:
        """TensorRT engine path tagged by GPU compute capability.

        Engines are hardware-locked, so each GPU gets its own file (e.g.
        `best_3class_v2.sm75.engine` for a GTX 1660). This makes the cache
        safe across machines without overwriting each other.
        """
        stem = Path(os.getenv("MODEL_FILE", "best_3class_v2.pt")).stem
        return self.engines_dir / f"{stem}.sm{compute_capability}.engine"

    @property
    def webhook_url(self) -> str:
        return f"{self.backend_url}{self.backend_api_ver}/webhooks/qualitycontrols"

    @property
    def canonical_events_url(self) -> str:
        return f"{self.backend_url}{self.backend_api_ver}/internal/vision/events"

    @property
    def upload_events_url(self) -> str:
        return f"{self.upload_api_url}{self.backend_api_ver}/internal/vision/events"
