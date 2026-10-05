"""Console composition root and the session/role guards every console route uses.

Split out of `routes/console.py` (batch 1, 2026-09-28) when that file passed
1,000 lines: wiring does not belong in a route module. Nothing here changed on
the way. `routes/console.py` re-exports these names because tests override
them by identity (`app.dependency_overrides[console.get_console_service]`).
"""
from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..core.config import Settings
from ..domain.operator_error import BELUM_MASUK, BUKAN_SUPPORT, INPUT_TIDAK_SAH, OperatorError
from ..domain.role import ROLE_SUPPORT, parse_allowed_roles
from ..domain.visit_manifest import detail_url_for
from ..integrations.erp.client import ErpClient
from ..integrations.erp.outbox_store import ErpOutboxStore
from ..integrations.notifications.line_client import LineClient
from ..integrations.upload.r2_uploader import R2Uploader
from ..license.manager import LicenseManager
from ..repositories.console_repository import ConsoleStore
from ..repositories.log_repository import LogStore
from ..repositories.riwayat_repository import RiwayatStore
from ..services.auth_service import AuthService
from ..services.bahaya_service import BahayaService
from ..services.console_service import ConsoleService
from ..services.dev_service import DevService
from ..services.erp_queue import ErpQueue
from ..services.gate_service import GateService
from ..services.impor_grading_service import ImporGradingService
from ..services.lapor_discord import LaporDiscord, rakit_lapor_discord
from ..services.operator_admin import OperatorAdmin
from ..services.pantau_antrean_line import PantauAntreanLine
from ..services.pembaruan_service import PembaruanService
from ..services.riwayat_service import RiwayatService
from ..services.scan_service import ScanService
from ..services.slip_grading import SlipGrading
from ..services.status_sinkron import StatusSinkron
from ..workers.master_data_worker import MasterDataWorker
from ..workers.visit_manifest_worker import VisitManifestWorker

logger = logging.getLogger(__name__)

SESSION_COOKIE = "konsol_sesi"


@lru_cache
def get_console_service() -> ConsoleService:
    """Console composition root. The only place these are wired."""
    settings = Settings()
    store = ConsoleStore(
        settings.console_db_path,
        erp_allowed_roles=parse_allowed_roles(settings.erp_allowed_roles_raw),
    )
    # Last Sync: SATU pencatat untuk semua worker dan layar (workers/cek_sinkron_worker.py).
    status_sinkron = StatusSinkron(
        store, erp_aktif=bool(settings.erp_url), r2_aktif=bool(settings.r2_bucket)
    )
    # The detail page does not depend on the AutoERP link: it exists whenever R2
    # is configured, regardless of whether ERP_URL is also set.
    manifest_worker = None
    if settings.r2_bucket and settings.r2_public_url:
        uploader = R2Uploader(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
        )
        manifest_worker = VisitManifestWorker(
            store,
            ErpOutboxStore(settings.state_dir / "manifest_outbox.db"),
            uploader,
            public_url=settings.r2_public_url,
            viewer_html=Path(__file__).resolve().parents[1] / "static" / "viewer.html",
            # `generated_at` in the manifest reads the mill's own clock, same as
            # every other FACTORY_TZ use here (§6.1) — not the container's UTC.
            clock=lambda: datetime.now(ZoneInfo(settings.factory_tz)).isoformat(),
            status=status_sinkron,
        )
    else:
        logger.info("Visit manifests off: R2_BUCKET or R2_PUBLIC_URL is empty")
    queue = ErpQueue(
        store,
        ErpOutboxStore(settings.erp_outbox_db_path),
        site=settings.erp_company,
        detail_url_for=(
            (lambda visit_id: detail_url_for(settings.r2_public_url, visit_id))
            if manifest_worker is not None
            else (lambda visit_id: None)
        ),
    )
    service = ConsoleService(
        settings,
        store,
        LineClient(settings),
        erp_queue=queue,
        manifest_queue=manifest_worker,
        status_sinkron=status_sinkron,
    )
    # Automatic assignment takes the same Update now lock as manual Tugaskan (rules 36, 38):
    # the SAME singleton the install route reads, or the two would not see each other.
    service.pakai_penjaga_pembaruan(get_pembaruan_service())
    return service


@lru_cache
def get_auth_service() -> AuthService:
    """Shares the console's store: one SQLite file, one lock."""
    return AuthService(get_console_service().store)


@lru_cache
def get_scan_service() -> ScanService:
    """Also shares the store — one SQLite file, one lock, like the auth service.

    Its own dependency rather than a method on `ConsoleService`: scanning only reads
    trucks, and keeping it apart is what stops it growing a second way to create one.
    """
    return ScanService(get_console_service().store)


@lru_cache
def get_gate_service() -> GateService:
    """Scan 1 and 4. Shares the store like the scan service; its own dependency so the one
    writer of gate times is not also a way to write weight. One instance on purpose: it
    holds the lock that serializes two scans of one QR."""
    console = get_console_service()
    return GateService(console.store, console.tz, console.hari_kerja)


@lru_cache
def get_dev_service() -> DevService:
    """Log store is its own SQLite file, not `console.db`: an error flood must
    not slow down the queries serving the operator screen. The line client and
    ERP outbox are shared with the console service — one connection each, not two.
    """
    service = get_console_service()
    settings = service.settings
    return DevService(
        LogStore(settings.log_db_path, retention_days=settings.log_retention_days),
        line_client=service.line_client,
        lines=service.lines,
        erp_outbox=service.erp_queue.outbox,
        # None whenever R2 is not configured (ConsoleService.manifest_queue is
        # None) — DevService.manifest_queue() reports that explicitly rather
        # than as an empty queue.
        manifest_outbox=(
            service.manifest_queue.outbox if service.manifest_queue is not None else None
        ),
        settings=settings,
        license_manager=_build_license_manager(settings),
        console_store=service.store,
    )


@lru_cache
def get_pantau_antrean_line() -> PantauAntreanLine:
    """Tab Status → Antrean line (batch 2.4). Klien line yang sama dengan konsol:
    satu cara memanggil line, satu `INTERNAL_SECRET`."""
    service = get_console_service()
    return PantauAntreanLine(service.line_client, service.lines)


@lru_cache
def get_lapor_discord() -> LaporDiscord:
    """Lapor galat ke Discord (batch 3.5). Satu store untuk handler, worker, dan layar;
    `store` None kalau `DISCORD_WEBHOOK_URL` kosong, bukan https, atau antreannya rusak."""
    return rakit_lapor_discord(get_console_service().settings)


def _build_license_manager(settings) -> LicenseManager | None:
    """The console's own verifier, or None if the feature is off.

    No `LicenseLocalRepo`: the clock ratchet belongs to the processes that can
    actually stop grading. A console with its own ratchet file would race the
    lines over the same SQLite for a number it only displays.

    A public key that will not load is swallowed to None rather than raised —
    this is wired at console startup, and a mill whose key is misconfigured
    needs a screen saying so, not a console that refuses to boot.
    """
    if not settings.lic_enabled:
        return None
    try:
        return LicenseManager(settings.lic_pubkey_pem, None, settings.lic_token)
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("Kunci publik lisensi tidak bisa dibaca: %s", exc)
        return None


@lru_cache
def get_bahaya_service() -> BahayaService:
    """Danger Zone (tab Setelan, support). Store, klien line, dan antrean milik
    konsol — satu koneksi masing-masing, bukan dua. Log store berkasnya sama
    dengan tab Log.

    Tarikan master data dirakit di sini, bukan meminjam worker yang sedang
    jalan: `build_erp_workers()` tidak menyimpan rujukan ke worker-nya. Dua
    tarikan bersamaan aman — upsert idempotent lewat lock store yang sama.
    """
    service = get_console_service()
    settings = service.settings
    tarik = None
    if settings.erp_url:
        klien = ErpClient(settings.erp_url, settings.erp_api_key, settings.erp_api_secret)
        tarik = MasterDataWorker(
            service.store, klien, interval_s=settings.console_sync_interval_s
        ).pull_once
    return BahayaService(
        service.store,
        LogStore(settings.log_db_path, retention_days=settings.log_retention_days),
        service.line_client,
        service.lines,
        service.erp_queue.outbox,
        service.manifest_queue.outbox if service.manifest_queue is not None else None,
        erp_aktif=bool(settings.erp_url),
        hash_bawaan=settings.console_default_hash,
        hash_support=settings.console_support_hash,
        # Hari kerja yang sama dengan strip "Hari ini" dan tab Timbangan.
        hari_kerja=service.today,
        tarik_master=tarik,
    )


@lru_cache
def get_operator_admin() -> OperatorAdmin:
    """Tab Akun (support). Store yang sama dengan login: satu berkas SQLite, satu lock,
    jadi akun yang baru dibuat langsung bisa dipakai masuk di gerbang."""
    return OperatorAdmin(get_console_service().store)


@lru_cache
def get_slip_service() -> SlipGrading:
    """Printable grading slip (batch 5.9). The store of the console, the company from
    `ERP_COMPANY` (empty on a site without AutoERP: the slip simply leaves it out)."""
    service = get_console_service()
    return SlipGrading(service.store, perusahaan=service.settings.erp_company)


@lru_cache
def get_riwayat_service() -> RiwayatService:
    """Tab Riwayat. Membaca `console.db` yang sama lewat koneksi baca-saja sendiri,
    bukan store konsol: query sebulan tidak boleh antre di lock yang dipakai
    menulis janjang dari line (`repositories/riwayat_repository.py`)."""
    service = get_console_service()
    return RiwayatService(
        RiwayatStore(service.settings.console_db_path),
        # Hari kerja yang sama dengan strip "Hari ini" dan tab Grading.
        hari_ini=service.today,
        zona=service.settings.factory_tz,
    )



@lru_cache
def get_impor_grading_service() -> ImporGradingService:
    """Impor CSV Per janjang (tab Riwayat, support). Menulis lewat store konsol yang
    sama dengan ingest, per potongan, jadi kiriman janjang dari line tidak menunggu
    satu impor besar selesai."""
    service = get_console_service()
    return ImporGradingService(
        service.store,
        lines=service.lines,
        zona=service.settings.factory_tz,
        # Hari kerja yang sama dengan strip "Hari ini": janjang hari ini tidak diimpor.
        hari_ini=service.today,
    )


@lru_cache
def get_pembaruan_service() -> PembaruanService:
    """Batch 4.6. Not built on get_console_service(): it needs only a folder, the running
    version and the factory clock, and route tests swap it without a console DB."""
    settings = Settings()
    zona = ZoneInfo(settings.factory_tz)
    return PembaruanService(
        settings.update_dir, lambda: settings.app_version, lambda: datetime.now(zona)
    )


def hangatkan_singleton() -> None:
    """Build, before the first request, EVERY `lru_cache` singleton in this module.

    Batch 2.5 moved login, `/state`, `dev/log` and `ingest_event` into the thread
    pool (the session check, a sync dependency, already ran there). `lru_cache` does
    not stop two threads from both building an instance on a first call that lands
    at the same moment: two `AuthService` objects would mean two login locks, and a
    burst of wrong passwords right after boot could get past the lockout again; two
    of any other service would mean two sets of whatever it guards. All of them, not
    just the ones a thread-pool route reaches today (a later `def` route would
    reopen the race); `tests/unit/test_hangatkan_singleton.py` fails when a new
    getter is not added here.
    """
    get_console_service()
    get_auth_service()
    get_scan_service()
    get_gate_service()
    get_dev_service()
    get_pantau_antrean_line()
    get_lapor_discord()
    get_bahaya_service()
    get_slip_service()
    get_operator_admin()
    get_riwayat_service()
    get_impor_grading_service()
    get_pembaruan_service()

Service = Annotated[ConsoleService, Depends(get_console_service)]
Auth = Annotated[AuthService, Depends(get_auth_service)]
Scan = Annotated[ScanService, Depends(get_scan_service)]
Gate = Annotated[GateService, Depends(get_gate_service)]
Dev = Annotated[DevService, Depends(get_dev_service)]
Bahaya = Annotated[BahayaService, Depends(get_bahaya_service)]
Admin = Annotated[OperatorAdmin, Depends(get_operator_admin)]
Riwayat = Annotated[RiwayatService, Depends(get_riwayat_service)]
Slip = Annotated[SlipGrading, Depends(get_slip_service)]
Impor = Annotated[ImporGradingService, Depends(get_impor_grading_service)]
Pembaruan = Annotated[PembaruanService, Depends(get_pembaruan_service)]


def require_operator(
    auth: Auth, konsol_sesi: Annotated[str | None, Cookie()] = None
) -> dict:
    """The operator behind the session cookie, or 401 with a code the gate words."""
    operator = auth.current(konsol_sesi)
    if operator is None:
        raise _operator_error(401, OperatorError(BELUM_MASUK, "belum masuk atau sesi habis"))
    return operator


Operator = Annotated[dict, Depends(require_operator)]


def require_support(operator: Operator) -> dict:
    """A support account, or 403.

    This is the actual guard on the developer screen; hiding its tab in
    console.html is tidiness, not security. Every `/api/console/dev/*` route
    goes through here so none can forget the check.
    """
    if operator.get("role") != ROLE_SUPPORT:
        raise _operator_error(
            403, OperatorError(BUKAN_SUPPORT, "menu ini untuk akun support")
        )
    return operator


Support = Annotated[dict, Depends(require_support)]


def _operator_error(status_code: int, exc: Exception) -> HTTPException:
    """Operator routes answer with a code the screen words in its own language.

    Machine lanes (events, scale program) keep a plain-text detail — see below.
    A refusal WITHOUT a code (a domain ValueError such as SetelanTidakSah) reaches the
    screen as the generic sentence that points to the Log tab (user decision 2026-10-01:
    no server text outside the Log tab), so its own text is logged here, once per refusal.
    """
    if isinstance(exc, OperatorError):
        return HTTPException(status_code=status_code, detail=exc.as_detail())
    logger.warning("Permintaan operator ditolak (HTTP %s): %s", status_code, exc)
    return HTTPException(status_code=status_code, detail=str(exc))


#: Only the operator lane answers in the screen's terms; the lines' machine lane keeps
#: FastAPI's default 422, because their outbox reads it.
_OPERATOR_PREFIX = "/api/console/"


def pasang_penangan_validasi(app: FastAPI) -> None:
    """A body of the wrong shape on an operator route: 400 `input_tidak_sah`.

    FastAPI's default is a 422 with a list of Pydantic errors, which the screen cannot word;
    every other operator refusal is 400 with a code, so this one is too (standard B1).
    """

    @app.exception_handler(RequestValidationError)
    async def _penangan(request: Request, exc: RequestValidationError) -> JSONResponse:
        if not request.url.path.startswith(_OPERATOR_PREFIX):
            return await request_validation_exception_handler(request, exc)
        errors = exc.errors()
        loc = errors[0]["loc"] if errors else ("body",)
        # `loc` is ("body", "qr") for a field, ("body",) for a body that is not an object,
        # and ("body", 17) for broken JSON; the screen labels the field through KAMUS.
        field = loc[1] if len(loc) > 1 and isinstance(loc[1], str) else "body"
        refusal = OperatorError(INPUT_TIDAK_SAH, f"isian tidak sah: {field}", field=field)
        return JSONResponse(status_code=400, content={"detail": refusal.as_detail()})
