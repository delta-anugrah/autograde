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
    # Empty string = "not set". docker-compose writes `${PLC_PORT:-}` so the
    # value can be derived from the protocol, and three containers shouting a
    # warning about that on every start would bury the real typos.
    if raw is None or not raw.strip():
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


#: Protocols this build can speak. "mc" is the live path since the ODOT
#: coupler was dropped; "modbus" stays for sites still wired through one.
PLC_PROTOCOLS = ("mc", "modbus")

#: Default TCP port per protocol. 1025 is the MC Protocol connection opened in
#: the CPU's Open Setting; 502 is Modbus-TCP.
_PLC_DEFAULT_PORT = {"mc": 1025, "modbus": 502}


def _plc_protocol() -> str:
    """`PLC_PROTOCOL`, normalised. Unknown or empty -> "mc" plus a warning."""
    raw = (os.getenv("PLC_PROTOCOL") or "").strip().lower()
    if not raw:
        return PLC_PROTOCOLS[0]
    if raw not in PLC_PROTOCOLS:
        logger.warning(
            "PLC_PROTOCOL=%r is not one of %s — falling back to %r",
            raw, ", ".join(PLC_PROTOCOLS), PLC_PROTOCOLS[0],
        )
        return PLC_PROTOCOLS[0]
    return raw


def _plc_port() -> int:
    """`PLC_PORT`, defaulting to whatever the chosen protocol listens on."""
    return _plc_int("PLC_PORT", _PLC_DEFAULT_PORT[_plc_protocol()])


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
    # Kosong atau 0 = "jangan patok, tanya sumbernya". Untuk file video itu satu-
    # satunya cara memutarnya pada kecepatan aslinya: `OpenCVCamera` cuma
    # membaca fps bawaan berkas kalau nilai ini tidak diisi. Kosong sengaja
    # diperlakukan seperti 0 dan BUKAN error — `.env.example` sendiri menyuruh
    # mengosongkannya, dan `int("")` menjatuhkan line saat start dengan pesan
    # yang tidak menyebut CAMERA_FPS sama sekali.
    camera_fps: int = field(
        default_factory=lambda: int(os.getenv("CAMERA_FPS", "20").strip() or 0)
    )
    camera_photo_path: str = field(default_factory=lambda: os.getenv("CAMERA_PHOTO_PATH", ""))

    # Nama berkas media (BUKAN path) yang dipilih layar Support, di-join ke
    # `/media` oleh `domain/sumber_kamera_resolver`. Menggantikan
    # CAMERA_VIDEO_PATH/CAMERA_PHOTO_PATH sebagai jalur yang dipakai layar;
    # keduanya masih dibaca supaya `.env` lama tetap jalan.
    media_file: str = field(default_factory=lambda: os.getenv("MEDIA_FILE", ""))

    # Folder media dan berkas setelannya — lihat `media_dir` / `media_env_path`
    # di bawah, yang menurunkan bawaannya dari `repo_root` saat env kosong.

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
    # Garis capture: x (px) dalam ruang STREAM (`STREAM_WIDTH`), bukan ruang
    # sensor. Janjang difoto saat kotaknya MENYENTUH garis ini — beda dari ROI,
    # yang menyaring wilayah dan memakai titik tengah. `0` = tidak ada garis,
    # dan itu perilaku sebelum fitur ini ada.
    # Ini cuma nilai awal: yang berlaku sehari-hari diatur dari layar support
    # konsol dan dikirim ke line lewat `/internal/setelan` tanpa restart.
    garis_capture: int = field(default_factory=lambda: int(os.getenv("GARIS_CAPTURE", "0")))
    # Sumbu garis capture: "tegak" (conveyor mendatar, garis vertikal, angka =
    # px dari kiri) atau "mendatar" (conveyor menurun, garis horizontal, angka
    # = px dari atas). Sama seperti `garis_capture`, ini cuma nilai awal.
    sumbu_garis: str = field(default_factory=lambda: os.getenv("SUMBU_GARIS", "tegak"))
    # Mode dev: angka confidence ikut digambar di kotak janjang. Nilai awal
    # saja; disetel dari layar support konsol.
    mode_dev: bool = field(default_factory=lambda: _as_bool(os.getenv("MODE_DEV"), False))

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

    # ── PLC (Mitsubishi MC Protocol, dulu ODOT CN-8031/Modbus) ───
    # Logic lives in src/palmgrade/plc/; the full address map is in
    # docs/plc-integration.md. Off by default — only a factory PC turns it on.
    # plc_coil_base is set per line by docker-compose.
    plc_enabled: bool = field(default_factory=lambda: _as_bool(os.getenv("PLC_ENABLED"), False))
    plc_host: str = field(default_factory=lambda: os.getenv("PLC_HOST", ""))
    # "mc" = straight to the CPU's built-in Ethernet port (the ODOT coupler was
    # dropped on 2026-09-21). "modbus" keeps the old coupler path alive for any
    # site still wired that way. An unknown value falls back to "mc" rather than
    # raising: same reason as _plc_int, a typo at 2am must not stop grading.
    plc_protocol: str = field(default_factory=lambda: _plc_protocol())
    # No single correct default: 1025 is the MC Protocol port opened in GX
    # Works2, 502 is Modbus. Deriving it from the protocol is what stops a
    # half-edited .env from dialling a port nobody is listening on.
    plc_port: int = field(default_factory=lambda: _plc_port())
    # Modbus only. MC Protocol addresses the CPU itself, so there is no unit id.
    plc_unit_id: int = field(default_factory=lambda: _plc_int("PLC_UNIT_ID", 1))
    # MC Protocol device letter the addresses below belong to. "M" (internal
    # relay) is what the panel allocates; a site that gets B or Y instead
    # changes this one value, not the callers.
    plc_device_prefix: str = field(
        default_factory=lambda: (os.getenv("PLC_DEVICE_PREFIX") or "M").strip().upper() or "M"
    )
    # Where the block we READ starts. Modbus discrete inputs start at 0; an M
    # block starts wherever the panel allocated it (Pak Ocit's list: 1100).
    plc_di_base: int = field(default_factory=lambda: _plc_int("PLC_DI_BASE", 0))
    plc_coil_base: int = field(default_factory=lambda: _plc_int("PLC_COIL_BASE", 0))
    # The "alive" bit PlcWorker holds ON. Per the ODOT schematic there is only
    # ONE for the whole PC — coil 9 (HEARTBIT PC ON), owned by line 1. Lines 2
    # and 3 stay empty: coils 10-15 are marked SPARE there, not ours to use.
    plc_coil_alive: tuple[int, ...] = field(
        default_factory=lambda: parse_coil_list(os.getenv("PLC_COIL_ALIVE"))
    )
    # How the PLC is told the PC is still alive. The correct answer DEPENDS ON
    # THE PROTOCOL, which is why the default is derived rather than fixed:
    #
    # - modbus (ODOT coupler): 0, held ON statically. That matches the
    #   schematic and Pak Ocit's ladder ("coil OFF means the PC is down"). A
    #   dead PC or cut LAN still shows up because the coupler's own fault
    #   action resets its outputs. Toggling here fires the "PC down" alarm
    #   every half period unless the ladder counts changes — that shipped once,
    #   in v1.3.0, and the mill saw the alarm all day.
    #
    # - mc (straight to the CPU): must BLINK. There is no coupler left to reset
    #   anything, so a bit left ON when the PC dies stays ON and its piston
    #   keeps firing. A blinking bit is the only thing the ladder can watch to
    #   notice we are gone — and there the ladder must count CHANGES, not level.
    plc_alive_toggle_ms: int = field(
        default_factory=lambda: _plc_int(
            "PLC_ALIVE_TOGGLE_MS", 500 if _plc_protocol() == "mc" else 0
        )
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

    # ------------------------------------------------------------------ sumber kamera

    def sumber_kamera(self) -> str:
        """Pilihan layar yang setara dengan `CAMERA_TYPE` + `MEDIA_FILE`.

        Kebalikan dari pemetaan di `domain/sumber_kamera`: `opencv` memetakan ke
        dua pilihan layar, dan berkaslah yang membedakan webcam dari video.

        Nilai `CAMERA_TYPE` asing jatuh ke `hikrobot`, tidak melempar: berkas
        yang disunting tangan dengan nilai ngawur harus tetap membuat line boot
        memakai kamera sungguhan. Yang rewel gerbang simpan di konsol.

        Ditulis di sini, bukan diimpor dari `services/media_env_service`:
        `config.py` dibaca setiap proses termasuk line, dan tidak boleh
        bergantung pada lapis service.
        """
        camera_type = self.camera_type.strip().lower()
        berkas = (self.media_file or self.camera_video_path or self.camera_photo_path).strip()
        if camera_type == "photo":
            return "foto"
        if camera_type == "opencv":
            return "video" if berkas else "webcam"
        return "hikrobot"

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
                "Set R2_* in .env to enable it."
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
        """Folder tulisan line ini: gambar, sidecar JSON, outbox.

        `ARTIFACTS_DIR` menimpanya. Di Docker tiap line punya volume sendiri
        (`./artifacts/line-N:/app/artifacts`), jadi ketiganya menulis ke
        `/app/artifacts` tanpa pernah bertabrakan. Di jalur NATIVE (`make line`)
        tidak ada volume: tanpa env ini tiga line menulis ke satu folder yang
        sama, sementara konsol menyajikan `/captures/{line_code}` dari
        `artifacts/{line_code}` — jadi gambarnya tersimpan tapi tiap tautan di
        layar dijawab 404.
        """
        dari_env = os.getenv("ARTIFACTS_DIR", "").strip()
        return Path(dari_env) if dari_env else self.repo_root / "artifacts"

    @property
    def line_code(self) -> str:
        """Kode line ini (`line-1`…) untuk dibaca manusia.

        Diturunkan dari `MACHINE_ID` lewat peta yang SUDAH ada, bukan env baru:
        sebuah `LINE_CODE` tersendiri akan jadi sumber kebenaran kedua yang bisa
        berbeda dari `machine_id` tanpa ada yang sadar — dan `machine_id` itu
        yang dipakai konsol mencocokkan event, jadi yang menang bukan yang
        tertulis di nama berkas.

        Line yang `MACHINE_ID`-nya tidak dikenal (PKS dengan id sendiri) tetap
        dapat nama yang bisa dibedakan, bukan gagal: ini cuma label.
        """
        for kode, _nama, _port, mid in _CONSOLE_LINE_DEFAULTS:
            if mid == self.machine_id:
                return kode
        return f"line-{self.machine_id[:8]}" if self.machine_id else "line"

    @property
    def videos_dir(self) -> Path:
        """Folder rekaman video developer (layar Rekam Video, `role=support`).

        SENGAJA di luar `artifacts/`: rekaman ini bukan bukti grading dan TIDAK
        ikut retensi otomatis — dihapus manual oleh yang merekam. Menaruhnya di
        `artifacts/` membuat `BatchUploadWorker._retention()` menyapunya
        diam-diam, dan itu terjadi justru di tengah penelusuran masalah.

        Ini satu-satunya bagian fitur rekam yang tetap di `.env`, karena
        jalurnya berbeda antara container dan host dan karena itu harus bisa
        di-mount. Resolusi, fps, dan bitrate diatur dari layar developer.

        ⚠️ **Namanya `REKAMAN_DIR`, BUKAN `VIDEOS_DIR`** — jangan "dirapikan".
        `VIDEOS_DIR` pernah ada dan artinya **kebalikannya**: folder video
        **sumber** yang jadi masukan kamera (autograde#104), dibuang saat
        diganti `media/`. Ada test yang menjaga nama itu tidak kembali
        (`test_artifacts_per_line.py::test_satu_env_saja_untuk_video`), dan
        memakainya lagi untuk folder KELUARAN membuat dua hal berlawanan
        memakai satu nama di berkas `.env` yang sama.
        """
        dari_env = os.getenv("REKAMAN_DIR", "").strip()
        return Path(dari_env) if dari_env else self.repo_root / "videos"

    @property
    def media_dir(self) -> str:
        """Folder berkas video/foto yang boleh dipilih layar Sumber Kamera.

        Di Docker `MEDIA_DIR` diisi compose dan menunjuk `/media`, hasil mount
        `./media:/media`. Di jalur NATIVE tidak ada mount itu, jadi bawaannya
        turun ke `media/` di repo — bukan `/media`, yang tidak ada di macOS.

        Kenapa bawaan absolut itu berbahaya: `MediaLibrary` sengaja memulangkan
        daftar KOSONG untuk folder yang tidak ada (layar kosong bisa dibaca,
        layar gagal-muat tidak). Jadi menatap folder yang salah terlihat persis
        seperti folder yang memang belum diisi — nol galat, nol petunjuk. Sudah
        memakan waktu sekali, 2026-09-21.
        """
        dari_env = os.getenv("MEDIA_DIR", "").strip()
        return dari_env if dari_env else str(self.repo_root / "media")

    @property
    def media_env_path(self) -> str:
        """Berkas setelan sumber kamera per line, ditulis konsol.

        TERPISAH dari `.env`, yang memuat `LICENSE_TOKEN` / `R2_SECRET_ACCESS_KEY`
        / `WEBHOOK_SECRET` dan tidak pernah ditulis kode mana pun. Bawaannya
        mengikuti `media_dir`: `/config/media.env` di container, `media.env` di
        repo untuk jalur native.
        """
        dari_env = os.getenv("MEDIA_ENV_PATH", "").strip()
        return dari_env if dari_env else str(self.repo_root / "media.env")

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
        """Empty when there is no cloud API: the image in R2 is then the whole upload.
        palmgrade-api was switched off in 2026-09 (Opsi B); AutoERP takes one message
        per visit from the console, never per bunch."""
        if not self.upload_api_url:
            return ""
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
