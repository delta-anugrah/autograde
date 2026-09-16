from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


# Production license public key, baked into the image.
#
# One key pair serves every mill and it is never rotated, so putting it in each
# factory PC's `.env` only adds a manual step that can be missed — and was: the
# Lampung PC ran for months with no `LICENSE_*` at all, which means the guard
# checked nothing. Baked in, a new factory PC is protected from first boot.
#
# Safe to commit: a public key can only VERIFY a signature. Forging one needs
# the private key, and that never leaves the cloud API.
#
# `LICENSE_PUBLIC_KEY` still wins when set, so a developer laptop can use its
# own DEV key pair. palmgrade-api's `utils/license.ts` bakes the same constant.
LICENSE_PUBLIC_KEY_BAKED = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEARvT6i531BDKvqg/j4glZoIAgvuKofP87Q6gkodLizyM=\n"
    "-----END PUBLIC KEY-----\n"
)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _plc_int(name: str, default: int) -> int:
    """Forgiving `int(os.getenv(...))` — PLC fields ONLY, never anything else.

    The PLC is an optional subsystem, off by default, and its knobs
    (`PLC_PULSE_MS`, `PLC_POLL_MS`, ...) get edited on site at 2am during
    commissioning. A typo there raising ValueError inside `Settings()` would
    stop the container from starting at all, taking GRADING down for a feature
    that need not even run. A broken value falls back and shouts in the log.
    Non-PLC fields stay fail-fast on purpose: there, bad config must stop boot.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer — falling back to %s", name, raw, default)
        return default


def _plc_opt_int(name: str) -> int | None:
    """`PLC_COIL_MANUAL` / `PLC_DI_MANUAL`: empty or broken = feature off.

    Unlike `_plc_int`, no sensible default exists here: guessing a coil
    number means writing to an address that belongs to someone else on the panel.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not a number — manual piston disabled", name, raw)
        return None


def parse_coil_list(value: str | None) -> tuple[int, ...]:
    """'9,10' -> (9, 10). Empty OR broken -> () plus a warning. Never raises.

    Used only by `PLC_COIL_ALIVE`, and for the same reason as `_plc_int`: a
    trailing comma in `PLC_COIL_ALIVE=9,10,` must not hold the container down.
    Falling back to () turns this line's alive bit off, which shows up at the
    PLC as a bit that stopped toggling rather than as a silent failure.
    """
    if not value or not value.strip():
        return ()
    try:
        return tuple(int(part.strip()) for part in value.split(","))
    except ValueError:
        logger.warning(
            "PLC_COIL_ALIVE=%r is invalid — this line's alive bit is OFF. Format: '9,10'.",
            value,
        )
        return ()


# The committed default WEBHOOK_SECRET, also the docker-compose fallback. Fine
# for dev, MUST be replaced in production — see Settings.validate_for_runtime().
# Kept as one constant so it never spreads as a magic string.
_DEFAULT_WEBHOOK_SECRET = "supersecret123"


class LineEndpoint(NamedTuple):
    """One camera line as the operator console sees it.

    A value, not a dict: a typo in `line.machine_id` is caught, while
    `line["machine_id"]` only blows up at runtime, mid-shift.
    """

    line_code: str
    name: str
    port: int
    machine_id: str


# A mill always has three lines and docker-compose pins their ports. The default
# machine ids match compose exactly, so dev runs with no extra .env.
_CONSOLE_LINE_DEFAULTS: tuple[tuple[str, str, int, str], ...] = (
    ("line-1", "Line 1", 8001, "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01"),
    ("line-2", "Line 2", 8002, "a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02"),
    ("line-3", "Line 3", 8003, "ad5f7bb9-c06d-4e87-8282-ce450ae331ec"),
)


@dataclass(frozen=True)
class Settings:
    app_name: str = "Ripe Recognition API"
    environment: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    # Release tag baked in at deploy time (same pattern as palmgrade-api and
    # palmgrade-frontend). "unknown" locally, deliberately not an empty string:
    # a missing version must be distinguishable from one never set.
    app_version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "unknown"))
    # `line` (default) = a camera instance. `console` = the 4th instance, the
    # offline operator console (plan §4): no camera, no YOLO, no PLC. Chosen by
    # `entrypoint.sh` before uvicorn — a different app module, so the console
    # never imports torch/cv2 and a dead camera line cannot take the screen down.
    app_mode: str = field(default_factory=lambda: os.getenv("APP_MODE", "line"))
    # Bind host/port do NOT live here: `entrypoint.sh` runs uvicorn (host hardcoded
    # to 0.0.0.0, port from APP_PORT which docker-compose sets per line). Settings
    # is never read for binding — do not add host/port fields back.
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
    # Hikrobot camera serial (e.g. "DA9069810"). When set, stable by-serial
    # selection replaces device_index, so two lines cannot grab each other's
    # camera. Empty falls back to device_index (dev/webcam).
    camera_serial: str | None = field(
        default_factory=lambda: (os.getenv("CAMERA_SERIAL", "").strip() or None)
    )
    # `.mfs` (MVS Feature Save) pushed to the camera on every connect — this is
    # what sets the real frame rate, not `camera_fps` below.
    # Non-fatal: a failed load logs a warning and the line keeps grabbing.
    # Empty here means skip, but docker-compose substitutes
    # `config/camera/hikrobot.mfs` when LINE_<n>_FEATURE_FILE is unset or empty,
    # so commenting that env var out ENABLES the default instead of disabling it.
    camera_feature_file: str | None = field(
        default_factory=lambda: (os.getenv("CAMERA_FEATURE_FILE", "").strip() or None)
    )
    camera_video_path: str = field(default_factory=lambda: os.getenv("CAMERA_VIDEO_PATH", ""))
    # Loop the video until the line is stopped (performance runs). Off = play once.
    camera_video_loop: bool = field(default_factory=lambda: _as_bool(os.getenv("CAMERA_VIDEO_LOOP"), False))
    camera_width: int = field(default_factory=lambda: int(os.getenv("CAMERA_WIDTH", "320")))
    camera_height: int = field(default_factory=lambda: int(os.getenv("CAMERA_HEIGHT", "240")))
    # Safety net only: used when the camera cannot report its own rate (webcam,
    # video file). A Hikrobot line is paced by the .mfs, read back from the camera.
    camera_fps: int = field(default_factory=lambda: int(os.getenv("CAMERA_FPS", "20")))
    camera_photo_path: str = field(default_factory=lambda: os.getenv("CAMERA_PHOTO_PATH", ""))

    # Stream display resolution — only affects MJPEG stream, not saved captures
    stream_width: int = field(default_factory=lambda: int(os.getenv("STREAM_WIDTH", "1280")))
    stream_height: int = field(default_factory=lambda: int(os.getenv("STREAM_HEIGHT", "720")))
    stream_fps: int = field(default_factory=lambda: int(os.getenv("STREAM_FPS", "12")))

    # Line identification
    machine_id: str = field(default_factory=lambda: os.getenv("MACHINE_ID", ""))

    # License Guard
    lic_enabled: bool = field(default_factory=lambda: _as_bool(os.getenv("LICENSE_ENABLED"), False))
    # The operator installs the token with `palmgrade license <token>`. Env is
    # fixed when the container is created, so a new token needs
    # `palmgrade restart` — a reboot is NOT enough, it reuses the old container
    # with its old env.
    lic_token: str = field(default_factory=lambda: os.getenv("LICENSE_TOKEN", ""))
    # The env key name matches palmgrade-api exactly. Both now bake the same
    # default key too, so the variable is optional on both sides: whatever is
    # set wins, empty falls back to the baked key.
    lic_pubkey_pem: str = field(
        default_factory=lambda: (
            os.getenv("LICENSE_PUBLIC_KEY") or LICENSE_PUBLIC_KEY_BAKED
        ).replace("\\n", "\n")
    )

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

    # Cloud batch upload (R2 + cloud API). Every credential is a placeholder
    # until the bucket and domain exist. An empty R2_BUCKET makes the batch
    # worker a no-op — that is the off switch.
    upload_minute: int = field(default_factory=lambda: int(os.getenv("UPLOAD_MINUTE", "0")))
    r2_account_id: str = field(default_factory=lambda: os.getenv("R2_ACCOUNT_ID", ""))
    r2_access_key_id: str = field(default_factory=lambda: os.getenv("R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = field(default_factory=lambda: os.getenv("R2_SECRET_ACCESS_KEY", ""))
    r2_bucket: str = field(default_factory=lambda: os.getenv("R2_BUCKET", ""))
    r2_public_url: str = field(default_factory=lambda: os.getenv("R2_PUBLIC_URL", "").rstrip("/"))
    # The text POST goes to the CLOUD API. BACKEND_URL stays on the LOCAL API
    # (the realtime webhook).
    upload_api_url: str = field(default_factory=lambda: os.getenv("UPLOAD_API_URL", "").rstrip("/"))
    upload_api_secret: str = field(default_factory=lambda: os.getenv("UPLOAD_API_SECRET", ""))
    upload_max_items_per_tick: int = field(default_factory=lambda: int(os.getenv("UPLOAD_MAX_ITEMS_PER_TICK", "2000")))
    upload_retention_days: int = field(default_factory=lambda: int(os.getenv("UPLOAD_RETENTION_DAYS", "7")))
    # Free-disk floor. Age-based retention alone stops being enough once
    # UPLOAD_RETENTION_DAYS is measured in months: if throughput runs above
    # forecast the disk fills BEFORE the oldest item is due — and a full disk
    # means grading stops writing, not merely an archive running late.
    # 0 disables the guard (back to age-only behaviour).
    upload_disk_min_free_gb: float = field(default_factory=lambda: float(os.getenv("UPLOAD_DISK_MIN_FREE_GB", "20")))

    # ── Operator console (APP_MODE=console) ──────────────────────
    # Mill timezone. Used ONLY to derive `work_date` at ingest (§6.1): a
    # mill runs ~20 h a day ACROSS midnight, so a UTC day boundary cuts one
    # shift in two. Resolved once at boot — a bogus TZ must fail at startup
    # rather than quietly file months of rows under the wrong date.
    factory_tz: str = field(default_factory=lambda: os.getenv("FACTORY_TZ", "Asia/Jakarta"))
    console_sync_interval_s: int = field(default_factory=lambda: int(os.getenv("CONSOLE_SYNC_INTERVAL_S", "300")))
    # Base URL of each camera line as seen from inside the console container.
    # The console forwards assignment and manual-reject here. Defaults to
    # localhost because every container runs network_mode: host at the mill.
    console_line_host: str = field(default_factory=lambda: os.getenv("CONSOLE_LINE_HOST", "http://localhost").rstrip("/"))
    # The two accounts baked into every image (services/akun_bawaan.py): the mill's own
    # and ours for support. **Hashes, never passwords** — a factory PC is reachable over
    # AnyDesk and an image layer is readable by anyone holding the image. Passwords
    # differ per mill, generated at install time with `make hash-sandi`. Empty is
    # normal: a mill whose accounts all come from AutoERP seeds nothing.
    # ⚠️ docker-compose eats `$`; write `$$` for a literal one, or the hash arrives
    # truncated and the account is refused (deliberately loudly).
    console_default_hash: str = field(default_factory=lambda: os.getenv("CONSOLE_DEFAULT_HASH", ""))
    console_support_hash: str = field(default_factory=lambda: os.getenv("CONSOLE_SUPPORT_HASH", ""))
    # How long the fault log (support Log screen) is kept. A time limit, not a
    # row-count cap: a count cap would discard old rows exactly while errors
    # are flooding. ~300 bytes/row, so 180 days is ~10 MB.
    log_retention_days: int = field(default_factory=lambda: int(os.getenv("LOG_RETENSI_HARI", "180")))

    # ── AutoERP link ─────────────────────────────────────────────
    # The console calls AutoERP; AutoERP never calls in (a factory PC has no
    # inbound). Empty `ERP_URL` switches the link off, and the operator screen
    # never depends on it.
    erp_url: str = field(default_factory=lambda: os.getenv("ERP_URL", "").rstrip("/"))
    erp_api_key: str = field(default_factory=lambda: os.getenv("ERP_API_KEY", ""))
    erp_api_secret: str = field(default_factory=lambda: os.getenv("ERP_API_SECRET", ""))
    # AutoERP Company this mill books against. Empty lets AutoERP use its own
    # default company, which is right on a single-company site.
    erp_company: str = field(default_factory=lambda: os.getenv("ERP_COMPANY", ""))
    # Roles AutoERP is allowed to grant. Empty rejects all of them — the one
    # brake the factory side can pull without waiting on ERP to be fixed.
    erp_allowed_roles_raw: str = field(
        default_factory=lambda: os.getenv("ERP_ALLOWED_ROLES", "support")
    )

    # ── PLC / ODOT CN-8031 (Modbus-TCP) ──────────────────────────
    # Logic lives in src/palmgrade/plc/; the full coil map is in
    # docs/plc-integration.md. Off by default — only a factory PC turns it on.
    # plc_coil_base is 0/3/6 per line, set by docker-compose.
    plc_enabled: bool = field(default_factory=lambda: _as_bool(os.getenv("PLC_ENABLED"), False))
    plc_host: str = field(default_factory=lambda: os.getenv("PLC_HOST", ""))
    plc_port: int = field(default_factory=lambda: _plc_int("PLC_PORT", 502))
    plc_unit_id: int = field(default_factory=lambda: _plc_int("PLC_UNIT_ID", 1))
    plc_coil_base: int = field(default_factory=lambda: _plc_int("PLC_COIL_BASE", 0))
    # The "alive" bit PlcWorker holds ON. Per the ODOT schematic there is only
    # ONE for the whole PC — coil 9 (HEARTBIT PC ON), owned by line 1. Lines 2
    # and 3 stay empty: coils 10-15 are marked SPARE there, not ours to use.
    plc_coil_alive: tuple[int, ...] = field(
        default_factory=lambda: parse_coil_list(os.getenv("PLC_COIL_ALIVE"))
    )
    # 0 = held ON statically, matching the schematic and Pak Ocit's ladder
    # ("coil OFF means the PC is down, the error shows on the seven segment").
    # A dead PC or a cut LAN still shows up, through the coupler's fault action
    # resetting the outputs. > 0 toggles every N ms, which ALSO catches a hung
    # process whose socket is still open — but then the ladder must count
    # CHANGES, not level, or the "PC down" alarm fires every half period.
    plc_alive_toggle_ms: int = field(
        default_factory=lambda: _plc_int("PLC_ALIVE_TOGGLE_MS", 0)
    )
    plc_pulse_ms: int = field(default_factory=lambda: _plc_int("PLC_PULSE_MS", 200))
    plc_pulse_gap_ms: int = field(default_factory=lambda: _plc_int("PLC_PULSE_GAP_MS", 100))
    # How many pulses may be OWED per coil. This is a "how stale may a signal
    # get" knob, NOT capacity or reliability: every queue slot adds
    # (pulse+gap) ms of lateness, and a late signal lands on the wrong bunch.
    # 1 = at most one pulse owed, so staleness stays <= (pulse+gap).
    plc_queue_max: int = field(default_factory=lambda: _plc_int("PLC_QUEUE_MAX", 1))
    plc_poll_ms: int = field(default_factory=lambda: _plc_int("PLC_POLL_MS", 200))
    plc_di_count: int = field(default_factory=lambda: _plc_int("PLC_DI_COUNT", 16))

    # Manual piston (panel proposal; see docs/plc-handoff-commissioning.md).
    # Coil level per line: 1 = request piston open. Empty = feature off, which is
    # the correct state until Pak Ocit allocates coil 10/11/12.
    plc_coil_manual: int | None = field(default_factory=lambda: _plc_opt_int("PLC_COIL_MANUAL"))
    # DI confirmation from the PLC: this line's piston is actually open. Empty =
    # the screen can only show the request, marked "not confirmed by PLC".
    plc_di_manual: int | None = field(default_factory=lambda: _plc_opt_int("PLC_DI_MANUAL"))

    # ------------------------------------------------------------------ validation

    def validate_for_runtime(self) -> None:
        """Fail fast on misconfiguration that is dangerous in production.

        WEBHOOK_SECRET guards both directions between vision and palmgrade-api.
        When a production `.env` was left unset the service used to run happily
        on the committed default `supersecret123` with only a warning — anyone
        who had read the repo could post fake events or internal commands. In
        production we now refuse to start; development still allows the default
        (warning only) so the dev/opencv flow stays friction-free.
        """
        if self.environment == "production" and not self.r2_bucket:
            logger.warning(
                "R2_BUCKET is empty — cloud batch upload is disabled (no-op). "
                "Set R2_*/UPLOAD_API_* in .env to enable it."
            )
        if self.webhook_secret != _DEFAULT_WEBHOOK_SECRET:
            return
        if self.environment == "production":
            raise RuntimeError(
                "WEBHOOK_SECRET is still the public default under APP_ENV=production. "
                "Set it to a secret value (identical to palmgrade-api's) before deploying."
            )
        logger.warning("WEBHOOK_SECRET is the default — set it before a production deploy.")

    # ------------------------------------------------------------------ paths

    @property
    def artifacts_dir(self) -> Path:
        return self.repo_root / "artifacts"

    @property
    def state_dir(self) -> Path:
        """Operational state (SQLite manifests) — OUTSIDE the static /captures mount."""
        return self.repo_root / "state"

    @property
    def results_dir(self) -> Path:
        """The only artifact folder anything writes to."""
        return self.artifacts_dir / "results"

    @property
    def models_release_dir(self) -> Path:
        return self.repo_root / "models" / "release"

    @property
    def models_experiments_dir(self) -> Path:
        return self.repo_root / "models" / "experiments"

    @property
    def ripeness_model_path(self) -> Path:
        model_file = os.getenv("MODEL_FILE", "best.pt")
        return self.models_release_dir / model_file

    @property
    def engines_dir(self) -> Path:
        # Writable (models/ is mounted read-only) — TensorRT engines cached here.
        return self.repo_root / "engines"

    def engine_path_for_gpu(self, compute_capability: str) -> Path:
        """TensorRT engine path tagged by GPU compute capability.

        Engines are hardware-locked, so each GPU gets its own file (e.g.
        `best.sm75.engine` for a GTX 1660). This makes the cache
        safe across machines without overwriting each other.
        """
        stem = Path(os.getenv("MODEL_FILE", "best.pt")).stem
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

    @property
    def erp_outbox_db_path(self) -> Path:
        """Messages waiting for AutoERP — its own file, like the line outbox."""
        return self.state_dir / "erp_outbox.db"

    @property
    def console_db_path(self) -> Path:
        """The console's SQLite index (§6.2) — the console never scans directories."""
        return self.state_dir / "console.db"

    @property
    def log_db_path(self) -> Path:
        """Its own file, not a table in console.db — an error flood must not
        slow down the queries serving the operator screen."""
        return self.state_dir / "log_kejadian.db"

    @property
    def console_lines(self) -> tuple[LineEndpoint, ...]:
        """The three camera lines the console serves.

        `LINE_N_MACHINE_ID` is read HERE, not in the service: env may only enter
        through Settings (CLAUDE.md § Conventions). The values match what
        docker-compose sets for each line.
        """
        return tuple(
            LineEndpoint(
                code, name, port,
                os.getenv(f"LINE_{code[-1]}_MACHINE_ID", default_machine).strip(),
            )
            for code, name, port, default_machine in _CONSOLE_LINE_DEFAULTS
        )

    @property
    def plc_coil_ok(self) -> int:
        return self.plc_coil_base

    @property
    def plc_coil_ng(self) -> int:
        return self.plc_coil_base + 1

    @property
    def plc_coil_error(self) -> int:
        return self.plc_coil_base + 2
