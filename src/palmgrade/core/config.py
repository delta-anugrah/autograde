from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", "supersecret123"))
    internal_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", "supersecret123"))

    # Camera
    camera_type: str = field(default_factory=lambda: os.getenv("CAMERA_TYPE", "hikrobot"))
    camera_device_index: int = field(default_factory=lambda: int(os.getenv("CAMERA_DEVICE_INDEX", "0")))
    camera_video_path: str = field(default_factory=lambda: os.getenv("CAMERA_VIDEO_PATH", ""))
    camera_width: int = field(default_factory=lambda: int(os.getenv("CAMERA_WIDTH", "320")))
    camera_height: int = field(default_factory=lambda: int(os.getenv("CAMERA_HEIGHT", "240")))
    camera_fps: int = field(default_factory=lambda: int(os.getenv("CAMERA_FPS", "30")))
    camera_photo_path: str = field(default_factory=lambda: os.getenv("CAMERA_PHOTO_PATH", ""))

    # Stream display resolution — only affects MJPEG stream, not saved captures
    stream_width: int = field(default_factory=lambda: int(os.getenv("STREAM_WIDTH", "1280")))
    stream_height: int = field(default_factory=lambda: int(os.getenv("STREAM_HEIGHT", "720")))

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

    # Detection zone — direction-aware, works for all 4 conveyor orientations.
    # CONVEYOR_DIRECTION: rtl (right→left) | ltr (left→right) | ttb (top→bottom) | btt (bottom→top)
    # DETECTION_ENTRY_OFFSET: px from entry edge → where detection zone starts (blue line)
    # DETECTION_EXIT_OFFSET:  px from exit edge  → where object is considered exited (green line)
    # ENTRY_MARGIN: tolerance added to exit check to avoid spurious re-triggers at the boundary
    #
    # Production defaults tuned for Hikrobot RTL (~2448px wide).
    # Must be recalibrated in the field for each camera/line.
    conveyor_direction: str = field(default_factory=lambda: os.getenv("CONVEYOR_DIRECTION", "rtl").lower())
    detection_entry_offset: int = field(default_factory=lambda: int(os.getenv("DETECTION_ENTRY_OFFSET", "2200")))
    detection_exit_offset: int = field(default_factory=lambda: int(os.getenv("DETECTION_EXIT_OFFSET", "100")))
    entry_margin: int = field(default_factory=lambda: int(os.getenv("ENTRY_MARGIN", "100")))

    def __post_init__(self) -> None:
        valid_directions = {"rtl", "ltr", "ttb", "btt"}
        if self.conveyor_direction not in valid_directions:
            raise ValueError(
                f"CONVEYOR_DIRECTION='{self.conveyor_direction}' is invalid. "
                f"Must be one of: {sorted(valid_directions)}"
            )

    # Display / annotation
    border_thickness: int = field(default_factory=lambda: int(os.getenv("BORDER_THICKNESS", "2")))
    font_scale: float = field(default_factory=lambda: float(os.getenv("FONT_SCALE", "0.7")))
    font_thickness: int = field(default_factory=lambda: int(os.getenv("FONT_THICKNESS", "2")))
    roi_scale: float = field(default_factory=lambda: float(os.getenv("ROI_SCALE", "0.7")))

    # Scheduler upload
    upload_hour: int = field(default_factory=lambda: int(os.getenv("UPLOAD_HOUR", "0")))
    upload_minute: int = field(default_factory=lambda: int(os.getenv("UPLOAD_MINUTE", "0")))
    destination_upload: str = field(default_factory=lambda: os.getenv("DESTINATION_UPLOAD", ""))

    # ------------------------------------------------------------------ paths

    @property
    def artifacts_dir(self) -> Path:
        return self.repo_root / "artifacts"

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
        model_file = os.getenv("MODEL_FILE", "best_3class.pt")
        return self.models_release_dir / model_file

    @property
    def webhook_url(self) -> str:
        return f"{self.backend_url}{self.backend_api_ver}/webhooks/qualitycontrols"

    @property
    def canonical_events_url(self) -> str:
        return f"{self.backend_url}{self.backend_api_ver}/internal/vision/events"
