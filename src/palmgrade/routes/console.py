"""Operator console routes. Mounted ONLY by `console_main.py`.

Deliberately route → service → repository with no pass-through controller: the
controller layer in this repo only forwards arguments, and the console has no
logic that needs an idle stop in between.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse

from ..core.config import Settings
from ..domain.operator_auth import SESSION_TTL_S
from ..domain.operator_error import BELUM_MASUK, BUKAN_SUPPORT, TERKUNCI, OperatorError
from ..domain.role import ROLE_SUPPORT, parse_allowed_roles
from ..domain.setelan_grading import SetelanTidakSah
from ..integrations.erp.outbox_store import ErpOutboxStore
from ..integrations.notifications.line_client import LineClient, LineUnavailable
from ..repositories.console_repository import ConsoleStore
from ..repositories.log_repository import LogStore
from ..services.auth_service import AuthService
from ..services.console_service import ConsoleService
from ..services.dev_service import CoilTidakDikenal, DevService, KonfirmasiKurang, PlcSibuk
from ..services.erp_queue import ErpQueue
from ..services.qr_cetak import png_qr
from ..services.scan_service import ScanService

_CONSOLE_HTML = Path(__file__).resolve().parents[1] / "static" / "console.html"
SESSION_COOKIE = "konsol_sesi"


@lru_cache
def get_console_service() -> ConsoleService:
    """Console composition root. The only place these are wired."""
    settings = Settings()
    store = ConsoleStore(
        settings.console_db_path,
        erp_allowed_roles=parse_allowed_roles(settings.erp_allowed_roles_raw),
    )
    queue = ErpQueue(
        store, ErpOutboxStore(settings.erp_outbox_db_path), site=settings.erp_company
    )
    return ConsoleService(settings, store, LineClient(settings), erp_queue=queue)


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
        settings=settings,
    )


Service = Annotated[ConsoleService, Depends(get_console_service)]
Auth = Annotated[AuthService, Depends(get_auth_service)]
Scan = Annotated[ScanService, Depends(get_scan_service)]
Dev = Annotated[DevService, Depends(get_dev_service)]


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
    """
    detail = exc.as_detail() if isinstance(exc, OperatorError) else str(exc)
    return HTTPException(status_code=status_code, detail=detail)


# ── operator screen + its API ───────────────────────────────────────────
# Every operator lane needs a session (Fase 4, plan §6.5). Open on purpose: the page
# itself (it draws the sign-in gate), the accounts the gate offers, and signing in.
# The machine lanes below keep the webhook secret and never see a cookie.
router = APIRouter(tags=["console"])


@router.get("/console", include_in_schema=False)
async def console_page() -> FileResponse:
    return FileResponse(_CONSOLE_HTML, media_type="text/html")


@router.get("/api/console/operators")
async def console_operators(auth: Auth) -> dict:
    """Read before anyone is signed in, so emails and names only — never a hash.

    The gate uses it to fill the email field on a touchscreen where typing an address is
    slow. The password is still required, so this is a convenience, not a way in.
    """
    return {"items": auth.operators()}


@router.post("/api/console/login")
async def login(auth: Auth, response: Response, payload: Annotated[dict, Body()]) -> dict:
    try:
        token, operator = auth.login(
            str(payload.get("email") or ""), str(payload.get("sandi") or "")
        )
    except OperatorError as exc:
        raise _operator_error(429 if exc.code == TERKUNCI else 401, exc) from exc
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_S,
        httponly=True,
        samesite="strict",
        path="/",
        # No `secure`: the factory console is plain HTTP on the LAN, and a Secure
        # cookie would simply never be sent back.
    )
    return {"operator": operator}


@router.post("/api/console/logout")
async def logout(
    auth: Auth, response: Response, konsol_sesi: Annotated[str | None, Cookie()] = None
) -> dict:
    auth.logout(konsol_sesi)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/api/console/me")
async def console_me(operator: Operator) -> dict:
    return {
        "operator": {
            "id": operator["operator_id"],
            "email": operator["email"],
            "full_name": operator["full_name"],
            "role": operator["role"],
        }
    }


@router.get("/api/console/state")
async def console_state(service: Service, operator: Operator) -> dict:
    return service.state()


@router.get("/api/console/history")
async def console_history(
    service: Service,
    operator: Operator,
    work_date: str | None = None,
    line_code: str | None = None,
    truck_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    resolved_date = work_date or service.today()
    # `items` keeps its shape; `total` is added beside it so the screen can page without
    # a second round trip, and older callers that only read `items` are unaffected.
    page = service.history_halaman(
        resolved_date, line_code=line_code, truck_id=truck_id, limit=limit, offset=offset
    )
    return {"work_date": resolved_date, **page}


@router.get("/api/console/trucks")
async def console_trucks(service: Service, operator: Operator) -> dict:
    return {"items": service.trucks()}


@router.post("/api/console/trucks", status_code=201)
async def register_manual_truck(
    service: Service, operator: Operator, payload: Annotated[dict, Body()]
) -> dict:
    """Borrowed or unregistered truck, typed by the operator (not from cloud master)."""
    try:
        return service.register_manual_truck(
            str(payload.get("plate_number") or ""),
            supplier_id=payload.get("supplier_id"),
            capacity=payload.get("capacity"),
        )
    except ValueError as exc:
        raise _operator_error(400, exc) from exc


@router.post("/api/console/scan")
async def console_scan(
    scan: Scan, operator: Operator, payload: Annotated[dict, Body()]
) -> dict:
    """One QR read at the weighbridge gate → the truck it belongs to.

    Behind the gate like every operator lane: the answer says which truck just
    arrived, which is mill operations, not public data.

    A plate that is not registered is **200 with `ditemukan: false`**, not 404: a
    borrowed truck is the normal case this exists for, and 404 would read on screen
    like something is broken. The screen offers manual entry instead.

    Anything that is not a plate is 400 — a parking receipt or promo QR that happens
    to get scanned must never turn into a ghost truck in master data.
    """
    try:
        return scan.search(str(payload.get("qr") or ""))
    except OperatorError as exc:
        raise _operator_error(400, exc) from exc


@router.post("/api/console/scan/keluar")
async def console_scan_exit(
    scan: Scan, service: Service, operator: Operator, payload: Annotated[dict, Body()]
) -> dict:
    """The second scan, at the exit gate: which ticket is waiting for its tare.

    The operator scans the plate and the console finds the ticket, instead of the
    operator hunting for that truck's row among the day's tickets.

    **Two open tickets are refused, not guessed** (operator's decision, 2026-09-15):
    guessing here can attach the tare to the wrong visit and mix two visits' tonnage —
    the same shape as the ticket-adoption bug we reported to AutoERP. The screen shows
    both and the operator picks.
    """
    try:
        return scan.open_ticket(str(payload.get("qr") or ""), service.today())
    except OperatorError as exc:
        raise _operator_error(400, exc) from exc


@router.get("/api/console/trucks/{plate_number}/qr.png", include_in_schema=False)
async def console_truck_qr(plate_number: str, operator: Operator) -> Response:
    """The QR card image for one plate, built here rather than in the browser.

    No CDN library: `console.html` has zero `https://` references on purpose, because
    the screen has to keep working while the internet is down — and a QR that fails to
    load means the weighbridge gate stops.

    Works for a plate that is not registered yet: the card is printed first and the
    truck registered later, which is the normal order for a new truck. Refusing here
    would force backoffice to register before they can print, for a code that only ever
    contains the plate.
    """
    try:
        image = png_qr(plate_number)
    except OperatorError as exc:
        raise _operator_error(400, exc) from exc
    # Cached by the browser: the card for one plate never changes, and the print page
    # asks for every truck at once.
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/api/console/weighings")
async def console_weighings(
    service: Service,
    operator: Operator,
    work_date: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    resolved_date = work_date or service.today()
    return {"work_date": resolved_date, "items": service.weighings(resolved_date, limit=limit)}


@router.get("/api/console/recap")
async def console_recap(
    service: Service, operator: Operator, work_date: str | None = None
) -> dict:
    """What the supplier is handed: bunches and neto per truck for one day."""
    resolved_date = work_date or service.today()
    return {"work_date": resolved_date, "items": service.recap(resolved_date)}


@router.post("/api/console/weighings", status_code=201)
async def record_weighing_manual(
    service: Service, operator: Operator, payload: Annotated[dict, Body()]
) -> dict:
    """Operator types bruto/tara by hand; the payload shape is identical to the
    scale program's. This lane keeps weighing tickets flowing while the scale
    program's format is unknown (docs/PERTANYAAN-TERBUKA.md X1).
    """
    try:
        return service.record_weighing(payload)
    except ValueError as exc:
        raise _operator_error(400, exc) from exc


@router.post("/api/console/lines/{line_code}/assign-truck")
async def assign_truck(
    line_code: str,
    service: Service,
    operator: Operator,
    truck_id: Annotated[str, Body(embed=True)],
) -> dict:
    try:
        return await service.assign_truck(line_code, truck_id)
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


@router.post("/api/console/lines/{line_code}/release-truck")
async def release_truck(line_code: str, service: Service, operator: Operator) -> dict:
    """Truck leaves. The line is told too — see `ConsoleService.lepas_truk`."""
    try:
        return await service.release_truck(line_code)
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


@router.post("/api/console/lines/{line_code}/manual-reject")
async def manual_reject(line_code: str, service: Service, operator: Operator) -> dict:
    """Recorded against whoever is signed in. It used to be the literal "operator"
    from the request body, which left the one action with a name on it anonymous."""
    try:
        return await service.manual_reject(line_code, operator["full_name"])
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


@router.post("/api/console/lines/{line_code}/piston")
async def piston(line_code: str, service: Service, open: Annotated[bool, Body(embed=True)]) -> dict:
    try:
        return await service.piston(line_code, open)
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


# ── developer lanes (support only) ───────────────────────────────────────
# Every `/api/console/dev/*` route depends on `Support`, never `Operator` directly —
# one chokepoint so a later lane cannot forget the guard.


@router.get("/api/console/dev/ping")
async def dev_ping(operator: Support) -> dict:
    """Lightest developer lane — used by the screen to confirm access still works."""
    return {"status": "ok"}


@router.get("/api/console/dev/log")
async def dev_log(
    dev: Dev,
    operator: Support,
    level: Annotated[str | None, Query()] = None,
    cari: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    return dev.log(level=level, search=cari, limit=limit, offset=offset)


@router.get("/api/console/dev/diagnostik")
async def dev_diagnostics(dev: Dev, operator: Support) -> dict:
    return await dev.diagnostics()


@router.get("/api/console/dev/antrean")
async def dev_queue(dev: Dev, operator: Support) -> dict:
    return dev.queue()


@router.post("/api/console/dev/antrean/kirim-ulang")
async def dev_resend(dev: Dev, operator: Support) -> dict:
    return dev.resend()


@router.get("/api/console/dev/versi")
async def dev_version(dev: Dev, operator: Support) -> dict:
    return dev.version()


@router.get("/api/console/dev/setelan")
async def dev_setelan_baca(service: Service, operator: Support) -> dict:
    """Setelan grading yang sedang berlaku, menurut konsol."""
    return service.setelan_grading()


@router.post("/api/console/dev/setelan")
async def dev_setelan_simpan(
    service: Service, operator: Support, payload: Annotated[dict, Body()]
) -> dict:
    """Ubah CONF_THRESHOLD/MINIMUM_SIZE untuk SEMUA line, tanpa restart.

    `role=support` saja (lane dev), dan tiap perubahan dicatat WARNING menyebut
    siapa yang mengubah — angka ini menentukan janjang dibuang atau lolos, jadi
    harus ada jejaknya kalau tonase sehari terlihat aneh.
    """
    try:
        return await service.simpan_setelan_grading(
            payload, diubah_oleh=operator["email"]
        )
    except SetelanTidakSah as exc:
        raise _operator_error(400, exc) from exc


@router.get("/api/console/dev/plc/{line_code}")
async def dev_plc(dev: Dev, operator: Support, line_code: str) -> dict:
    """DI snapshot + testable coils for one line. Read-only — safe to open anytime,
    including PLC_ENABLED=false (the normal dev/cloud state): the line answers
    `{"enabled": false}` rather than erroring, and the screen says so."""
    try:
        return await dev.plc_read(line_code)
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


@router.post("/api/console/dev/plc/{line_code}/coil")
async def dev_plc_coil(
    dev: Dev,
    operator: Support,
    line_code: str,
    coil: Annotated[int, Body()],
    konfirmasi: Annotated[str, Body()],
) -> dict:
    """The only lane in this whole console that moves physical hardware.

    Three guards: typed confirmation, refused while the line is processing a
    truck (409, checked on the line — see DevService.plc_fire), and every
    attempt — fired or refused — leaves a WARNING row in event_log.
    """
    try:
        return await dev.plc_fire(
            line_code=line_code,
            coil=coil,
            konfirmasi=konfirmasi,
            operator_email=operator["email"],
        )
    except KonfirmasiKurang as exc:
        raise _operator_error(400, exc) from exc
    except PlcSibuk as exc:
        raise _operator_error(409, exc) from exc
    except CoilTidakDikenal as exc:
        raise _operator_error(422, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc
    except ValueError as exc:
        # Must come AFTER KonfirmasiKurang/CoilTidakDikenal above — both are
        # ALSO ValueError (via OperatorError, ValueError), and a bare catch
        # placed first would swallow them into the wrong status code.
        raise _operator_error(404, exc) from exc


# ── event receiver for the three lines (frozen contract §5) ─────────────
# URL and header shape MUST match palmgrade-api: the sender is the line's
# OutboxRetryWorker, which is not modified at all.
ingest_router = APIRouter(tags=["ingest"])


@ingest_router.post("/internal/vision/events", status_code=201)
async def ingest_event(
    service: Service,
    payload: Annotated[dict, Body()],
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict:
    if x_webhook_secret != service.settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        work_date = service.ingest(payload)
    except ValueError as exc:
        # 400 → the line's outbox holds it and marks it failed. Not 200 on
        # purpose: a malformed event must be visible, not vanish.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "work_date": work_date}


@ingest_router.post("/internal/scale/weighing", status_code=201)
async def ingest_weighing(
    service: Service,
    payload: Annotated[dict, Body()],
    x_webhook_secret: Annotated[str | None, Header()] = None,
) -> dict:
    """Scale program payload (§3.5c). Same secret as the event lane.

    The real format is unknown (docs/PERTANYAAN-TERBUKA.md X1); what is frozen
    here is our shape — `plate_number`, `gross_kg`, `tare_kg`, `entered_at`,
    `exited_at`, optional `ref`. An adapter follows once the format lands.
    """
    if x_webhook_secret != service.settings.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        return service.record_weighing(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
