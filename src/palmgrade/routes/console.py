"""Operator console routes. Mounted ONLY by `console_main.py`.

Deliberately route → service → repository with no pass-through controller: the
controller layer in this repo only forwards arguments, and the console has no
logic that needs an idle stop in between.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Cookie, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from ..domain import impor_grading
from ..domain.bahaya import HapusBerjalan
from ..domain.operator_auth import SESSION_TTL_S
from ..domain.operator_error import (
    AKUN_DIRI_SENDIRI,
    AKUN_MILIK_ERP,
    AKUN_SUDAH_ADA,
    AKUN_TIDAK_ADA,
    IMPOR_TERLALU_BESAR,
    TERKUNCI,
    InvalidInput,
    OperatorError,
)
from ..domain.pilihan_model import ModelTidakSah
from ..domain.setelan_grading import SetelanTidakSah
from ..domain.setelan_rekam import SetelanRekamTidakSah
from ..domain.sumber_kamera import SumberTidakSah
from ..integrations.notifications.line_client import LinePlcTolak, LineUnavailable
from ..services.bahaya_service import BahayaDitolak, BahayaSemuaMenolak, BahayaTidakSah
from ..services.dev_service import CoilTidakDikenal, PlcSibuk
from ..services.impor_grading_service import ImporDitolak, ImporTidakAda
from ..services.qr_cetak import png_qr
from ..services.riwayat_service import RiwayatService

# Wiring and guards live in console_deps.py. The `x as x` form re-exports them:
# tests override these by identity and have imported them from here since Fase 4.
from .console_deps import SESSION_COOKIE as SESSION_COOKIE
from .console_deps import Admin, Auth, Bahaya, Dev, Impor, Operator, Riwayat, Scan, Service, Support
from .console_deps import _operator_error as _operator_error
from .console_deps import get_auth_service as get_auth_service
from .console_deps import get_bahaya_service as get_bahaya_service
from .console_deps import get_console_service as get_console_service
from .console_deps import get_dev_service as get_dev_service
from .console_deps import get_impor_grading_service as get_impor_grading_service
from .console_deps import get_operator_admin as get_operator_admin
from .console_deps import get_riwayat_service as get_riwayat_service
from .console_deps import get_scan_service as get_scan_service
from .console_deps import require_operator as require_operator
from .console_deps import require_support as require_support

logger = logging.getLogger(__name__)

_CONSOLE_HTML = Path(__file__).resolve().parents[1] / "static" / "console.html"


# ── operator screen + its API ───────────────────────────────────────────
# Every operator lane needs a session (Fase 4, plan §6.5). Open on purpose: the page
# itself (it draws the sign-in gate), the accounts the gate offers, and signing in.
# The machine lanes below keep the webhook secret and never see a cookie.
router = APIRouter(tags=["console"])

# Route yang memanggil SQLite berat dideklarasikan `def`, bukan `async def` (batch 2.5):
# FastAPI menjalankannya di thread pool, jadi query-nya tidak menahan event loop yang
# melayani layar lain dan kiriman janjang dari tiga line. Route yang juga harus `await`
# membungkus bagian sinkronnya dengan `run_in_threadpool`. Pola yang sama dengan tab Rekap.


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
def login(auth: Auth, response: Response, payload: Annotated[dict, Body()]) -> dict:
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
async def console_state(service: Service, dev: Dev, operator: Operator) -> dict:
    """Ringkasan hari kerja, plus keadaan langganan untuk banner operator.

    Menumpang di sini, bukan endpoint sendiri: layar sudah memanggil ini tiap 2
    detik, jadi banner ikut hidup tanpa satu pun request tambahan.

    Sengaja **bukan** lewat `/api/console/dev/*`: banner ini untuk operator
    biasa, yang justru orang yang akan melihat kamera berhenti. Yang dikirim di
    sini cuma tanggal, tingkat keparahan, dan nama perusahaan — nomor token tetap
    support-only. `versi` ikut untuk baris di bawah tulisan AUTOGRADE (2026-09-28):
    dibaca tiap polling, jadi sesudah `autograde pull` layar yang terbuka ikut
    menampilkan versi baru tanpa dimuat ulang.

    `service.state()` jalan di thread pool (batch 2.5): polling 2 detik ini membaca
    beberapa query SQLite, dan di event loop query itu menahan layar lain dan kiriman
    janjang dari tiga line.
    """
    return {
        **(await run_in_threadpool(service.state)),
        "lisensi": await dev.license_state(),
        "versi": dev.app_version(),
    }


@router.get("/api/console/history")
def console_history(
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


# ── tab Riwayat (2026-09-26) ────────────────────────────────────────────
# Grading hari-hari sebelumnya, untuk operator biasa (bukan lane support), sama
# dengan tab Grading dan Rekap. Keduanya `def`, bukan `async def`: query sebulan
# memakan detik, dan di thread pool itu tidak menahan loop yang melayani layar
# lain dan kiriman janjang dari line.
TampilanRiwayat = Literal["hari", "truk", "janjang"]
HasilRiwayat = Literal["", "ripe", "unripe", "jk", "tp"]


def _filter_riwayat(riwayat: RiwayatService, **isian: str | None):
    try:
        return riwayat.filter(**isian)
    except ValueError as exc:
        raise _operator_error(400, exc) from exc


@router.get("/api/console/riwayat")
def console_riwayat(
    riwayat: Riwayat,
    operator: Operator,
    dari: str | None = None,
    sampai: str | None = None,
    line_code: str | None = None,
    plat: str | None = None,
    hasil: HasilRiwayat = "",
    tampilan: TampilanRiwayat = "hari",
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ringkasan: bool = True,
) -> dict:
    """Satu tampilan (per hari / per truk / per janjang) untuk rentang maks 31 hari.

    Per hari dan per truk dikirim utuh dan dibagi halaman di layar; `limit` dan
    `offset` cuma berlaku untuk per janjang. `ringkasan=false` saat layar cuma
    pindah halaman atau tampilan: angkanya tidak berubah, dan menghitungnya ulang
    berarti memindai rentang itu lagi.
    """
    f = _filter_riwayat(riwayat, dari=dari, sampai=sampai, line_code=line_code, plat=plat, hasil=hasil)
    return riwayat.halaman(f, tampilan=tampilan, limit=limit, offset=offset, ringkasan=ringkasan)


@router.get("/api/console/riwayat/csv")
def console_riwayat_csv(
    riwayat: Riwayat,
    operator: Operator,
    dari: str | None = None,
    sampai: str | None = None,
    line_code: str | None = None,
    plat: str | None = None,
    hasil: HasilRiwayat = "",
    tampilan: TampilanRiwayat = "hari",
    bahasa: Literal["id", "en"] = "id",
) -> StreamingResponse:
    """Semua baris filter itu sebagai CSV (bukan cuma halaman yang terlihat),
    dialirkan per potongan: sebulan janjang tidak pernah utuh di memori."""
    f = _filter_riwayat(riwayat, dari=dari, sampai=sampai, line_code=line_code, plat=plat, hasil=hasil)
    nama, isi = riwayat.csv(f, tampilan=tampilan, bahasa=bahasa)
    return StreamingResponse(
        isi,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nama}"', "Cache-Control": "no-store"},
    )


@router.get("/api/console/trucks")
def console_trucks(service: Service, operator: Operator) -> dict:
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
def console_weighings(
    service: Service,
    operator: Operator,
    work_date: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    resolved_date = work_date or service.today()
    return {"work_date": resolved_date, "items": service.weighings(resolved_date, limit=limit)}


@router.get("/api/console/recap")
def console_recap(
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
        return await service.record_weighing(payload)
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
    except HapusBerjalan as exc:
        raise _operator_error(409, exc) from exc
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
async def piston(
    line_code: str, service: Service, operator: Operator, open: Annotated[bool, Body(embed=True)]
) -> dict:
    """Moves hardware, so behind the session like every operator lane (batch 1.1),
    and recorded against whoever is signed in, like manual-reject."""
    try:
        return await service.piston(
            line_code, open, requested_by=operator["full_name"] or operator["email"]
        )
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
def dev_log(
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


@router.get("/api/console/dev/antrean/manifest")
async def dev_manifest_queue(dev: Dev, operator: Support) -> dict:
    """Second row on the same screen: the R2 manifest queue (a separate
    `ErpOutboxStore`, see VisitManifestWorker). `{"aktif": false}` when R2 is
    not configured — the screen must say so, not show zeros."""
    return dev.manifest_queue()


@router.get("/api/console/dev/versi")
async def dev_version(dev: Dev, operator: Support) -> dict:
    return await dev.version()


@router.get("/api/console/dev/akun")
async def dev_akun(dev: Dev, operator: Support) -> dict:
    """Akun yang bisa masuk konsol di PC ini, tanpa hash sandi."""
    return dev.akun()


#: Penolakan tab Akun yang bukan salah isian. Sisanya 400: email, nama, atau sandi
#: yang tidak lolos aturan.
_AKUN_STATUS = {
    AKUN_TIDAK_ADA: 404,
    AKUN_SUDAH_ADA: 409,
    AKUN_MILIK_ERP: 409,
    AKUN_DIRI_SENDIRI: 409,
}


def _akun_ditolak(exc: OperatorError) -> HTTPException:
    return _operator_error(_AKUN_STATUS.get(exc.code, 400), exc)


# Empat aksi tab Akun (2026-09-26, membalik "tidak ada lane web" di aturan 19).
# Semuanya `def`, bukan `async def`: sandi di-hash dengan scrypt yang sengaja
# lambat, dan di thread pool itu tidak menahan loop yang melayani layar lain dan
# kiriman janjang dari line. Yang menjaga tetap `require_support`; akun AutoERP
# ditolak di `OperatorAdmin`, bukan cuma disembunyikan tombolnya.
@router.post("/api/console/dev/akun", status_code=201)
def dev_akun_tambah(
    admin: Admin,
    operator: Support,
    email: Annotated[str, Body()] = "",
    nama: Annotated[str, Body()] = "",
    sandi: Annotated[str, Body()] = "",
    sandi_ulang: Annotated[str, Body()] = "",
    role: Annotated[str, Body()] = "",
) -> dict:
    """Akun LOKAL baru. Email yang sudah ada ditolak, tidak diganti sandinya."""
    try:
        akun = admin.tambah(email, nama, sandi, sandi_ulang, role, oleh=operator["email"])
    except OperatorError as exc:
        raise _akun_ditolak(exc) from exc
    return {"akun": akun}


@router.post("/api/console/dev/akun/sandi")
def dev_akun_sandi(
    admin: Admin,
    operator: Support,
    email: Annotated[str, Body()] = "",
    sandi: Annotated[str, Body()] = "",
    sandi_ulang: Annotated[str, Body()] = "",
) -> dict:
    """Sandi baru untuk akun lokal. Semua sesi akun itu berakhir saat itu juga."""
    try:
        admin.ganti_sandi(email, sandi, sandi_ulang, oleh=operator["email"])
    except OperatorError as exc:
        raise _akun_ditolak(exc) from exc
    return {"status": "ok"}


@router.post("/api/console/dev/akun/status")
def dev_akun_status(
    admin: Admin,
    operator: Support,
    aktif: Annotated[bool, Body()],
    email: Annotated[str, Body()] = "",
) -> dict:
    """Matikan (sesinya berakhir) atau hidupkan lagi akun lokal. Bukan akun sendiri.

    `aktif` wajib boolean: `bool("false")` bernilai True, jadi teks bebas ditolak
    422 alih-alih ditebak jadi "aktifkan".
    """
    try:
        return {"status": admin.atur_status(email, aktif, oleh=operator["email"])}
    except OperatorError as exc:
        raise _akun_ditolak(exc) from exc


@router.post("/api/console/dev/akun/role")
def dev_akun_role(
    admin: Admin,
    operator: Support,
    email: Annotated[str, Body()] = "",
    role: Annotated[str, Body()] = "",
) -> dict:
    """Ubah role akun lokal. Bukan akun sendiri: support yang menurunkan dirinya
    kehilangan layar ini di klik berikutnya."""
    try:
        return {"role": admin.atur_role(email, role, oleh=operator["email"])}
    except OperatorError as exc:
        raise _akun_ditolak(exc) from exc


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


#: Kode yang line pakai untuk menolak perintah rekam, dan pesan yang dibaca
#: support untuk masing-masing. Keduanya butuh tindakan berbeda, jadi TIDAK
#: diratakan jadi satu "gagal": 409 berarti keadaan sudah berubah (dua tab
#: terbuka, atau rekaman sudah berhenti sendiri), 507 berarti disk pabrik
#: menipis dan itu harus ditangani sekarang.
_REKAM_TOLAK = {
    409: "rekam_keadaan_berubah",
    507: "rekam_disk_mepet",
}


def _rekam_ditolak(exc: LinePlcTolak):
    """Terjemahkan penolakan line jadi jawaban yang bisa dibaca layar.

    Tanpa ini `LinePlcTolak` naik apa adanya dan FastAPI menjawab **500** —
    terbaca seperti konsol rusak, padahal yang terjadi cuma "line itu memang
    tidak sedang merekam". Ditemukan di browser 2026-09-22.
    """
    kode = _REKAM_TOLAK.get(exc.status_code, "rekam_ditolak")
    return _operator_error(
        exc.status_code if exc.status_code in _REKAM_TOLAK else 502,
        OperatorError(kode, str(exc)[:200]),
    )


@router.get("/api/console/dev/rekam")
async def dev_rekam_status(service: Service, operator: Support) -> dict:
    """Status rekaman tiap line, setelan yang berlaku, dan sisa disk."""
    return await service.rekam_status_semua()


@router.post("/api/console/dev/rekam/setelan")
async def dev_rekam_setelan(
    service: Service, operator: Support, payload: Annotated[dict, Body()]
) -> dict:
    """Ubah resolusi rekaman. Berlaku untuk rekaman BERIKUTNYA.

    Sengaja tidak menyentuh rekaman yang sedang jalan: mengubah resolusi di
    tengah berkas MP4 menghasilkan berkas rusak.
    """
    try:
        return await service.simpan_setelan_rekam(payload, diubah_oleh=operator["email"])
    except SetelanRekamTidakSah as exc:
        raise _operator_error(400, exc) from exc


@router.post("/api/console/dev/rekam/{line_code}/mulai")
async def dev_rekam_mulai(line_code: str, service: Service, operator: Support) -> dict:
    """Mulai merekam satu line. Tiap penekanan dicatat WARNING menyebut siapa —
    rekaman menulis ke disk pabrik, jadi harus ada jejaknya."""
    try:
        return await service.rekam_mulai(line_code, diubah_oleh=operator["email"])
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LinePlcTolak as exc:
        raise _rekam_ditolak(exc) from exc


@router.post("/api/console/dev/rekam/{line_code}/stop")
async def dev_rekam_stop(line_code: str, service: Service, operator: Support) -> dict:
    try:
        return await service.rekam_stop(line_code, diubah_oleh=operator["email"])
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LinePlcTolak as exc:
        raise _rekam_ditolak(exc) from exc


@router.get("/api/console/dev/sumber-kamera")
async def dev_sumber_kamera_baca(service: Service, operator: Support) -> dict:
    """Sumber tiap line + daftar berkas yang boleh dipilih."""
    return service.sumber_kamera()


@router.post("/api/console/dev/sumber-kamera")
async def dev_sumber_kamera_simpan(
    service: Service, operator: Support, payload: Annotated[dict, Body()]
) -> dict:
    """Ubah sumber kamera per line, lalu restart line yang berubah.

    `role=support` saja: salah pilih membuat line berhenti grading. Tiap
    perubahan dicatat WARNING menyebut siapa yang mengubah.
    """
    try:
        return await service.simpan_sumber_kamera(
            payload, diubah_oleh=operator["email"]
        )
    except SumberTidakSah as exc:
        raise _operator_error(400, exc) from exc


@router.get("/api/console/dev/model-deteksi")
async def dev_model_deteksi_baca(service: Service, operator: Support) -> dict:
    """Model pilihan tiap line + semua model di `models/release` beserta kelasnya."""
    return await service.model_deteksi_async()


@router.post("/api/console/dev/model-deteksi")
async def dev_model_deteksi_simpan(
    service: Service, operator: Support, payload: Annotated[dict, Body()]
) -> dict:
    """Ganti model per line, lalu restart line yang berubah.

    `role=support` saja: model yang salah membuat line jalan tanpa menghitung.
    Tiap perubahan dicatat WARNING menyebut siapa yang mengubah.
    """
    try:
        return await service.simpan_model_deteksi(payload, diubah_oleh=operator["email"])
    except ModelTidakSah as exc:
        raise _operator_error(400, exc) from exc


# ── Danger Zone (tab Setelan, support) ─────────────────────────────────
# Lima aksi berbahaya. Semua lewat `require_support`, dan yang menghapus
# memeriksa ulang keadaan pabrik di server — layar cuma menjelaskan.
# Aturannya: CLAUDE.md aturan 25 (Danger Zone).


@router.get("/api/console/dev/bahaya")
async def dev_bahaya(bahaya: Bahaya, operator: Support) -> dict:
    """Angka, hambatan, dan peringatan untuk kelima panel Danger Zone."""
    return await bahaya.ringkasan()


@router.post("/api/console/dev/bahaya/restart-line")
async def dev_bahaya_restart(bahaya: Bahaya, operator: Support) -> dict:
    return await bahaya.restart_semua(oleh=operator["email"])


@router.post("/api/console/dev/bahaya/logout-semua")
async def dev_bahaya_logout(bahaya: Bahaya, operator: Support) -> dict:
    """Semua sesi, termasuk milik yang menekan — jawaban ini yang terakhir
    diterimanya sebelum layar kembali ke gerbang login."""
    return bahaya.logout_semua(oleh=operator["email"])


@router.post("/api/console/dev/bahaya/hapus-rekaman")
async def dev_bahaya_hapus_rekaman(
    bahaya: Bahaya,
    operator: Support,
    konfirmasi: Annotated[str, Body(embed=True)] = "",
) -> dict:
    try:
        return await bahaya.hapus_rekaman(konfirmasi=konfirmasi, oleh=operator["email"])
    except BahayaTidakSah as exc:
        raise _operator_error(400, exc) from exc


@router.post("/api/console/dev/bahaya/hapus-data")
async def dev_bahaya_hapus_data(
    bahaya: Bahaya,
    operator: Support,
    mode: Annotated[str, Body()] = "",
    konfirmasi: Annotated[str, Body()] = "",
) -> dict:
    """Hapus data transaksi (`mode=transaksi`) atau semua data (`mode=semua`).

    400 = konfirmasi salah / mode asing; 409 `bahaya_ditolak` = keadaan pabrik
    belum aman (`params.hambatan` berisi kodenya); 409 `semua_line_menolak` =
    tidak satu line pun menerima perintahnya (`params.lines`). Ketiganya tidak
    mengubah apa pun.
    """
    try:
        return await bahaya.hapus_data(mode=mode, konfirmasi=konfirmasi, oleh=operator["email"])
    except BahayaTidakSah as exc:
        raise _operator_error(400, exc) from exc
    except (BahayaDitolak, BahayaSemuaMenolak) as exc:
        raise _operator_error(409, exc) from exc


# ── impor grading dari CSV (tab Riwayat, support) ────────────────────────
# Unduh CSV untuk semua operator; impor cuma support (keputusan user 2026-09-27).
# Berkasnya dikirim apa adanya sebagai badan permintaan, tanpa multipart, dan
# ukurannya dibatasi SEBELUM dibaca utuh. Pembacaannya di thread pool: sebulan
# janjang bisa ratusan ribu baris, dan loop yang melayani layar tidak boleh diam.


async def _baca_berkas(request: Request) -> bytes:
    maks = impor_grading.MAKS_BYTE
    panjang = request.headers.get("content-length", "")
    if panjang.isdigit() and int(panjang) > maks:
        raise _berkas_terlalu_besar(maks)
    potongan: list[bytes] = []
    total = 0
    async for bagian in request.stream():
        total += len(bagian)
        if total > maks:
            raise _berkas_terlalu_besar(maks)
        potongan.append(bagian)
    return b"".join(potongan)


def _berkas_terlalu_besar(maks: int) -> HTTPException:
    return _operator_error(
        413, InvalidInput(IMPOR_TERLALU_BESAR, "berkas terlalu besar", maks_mb=maks // (1024 * 1024))
    )


def _impor_ditolak(exc: OperatorError) -> HTTPException:
    """404 batch tidak ada, 409 keadaan yang menolak, 413 terlalu besar, sisanya 400."""
    if isinstance(exc, ImporTidakAda):
        return _operator_error(404, exc)
    if isinstance(exc, ImporDitolak):
        return _operator_error(409, exc)
    return _operator_error(413 if exc.code == IMPOR_TERLALU_BESAR else 400, exc)


@router.post("/api/console/dev/riwayat/impor/periksa")
async def dev_impor_periksa(
    request: Request, impor: Impor, operator: Support, nama: str = Query("", max_length=200)
) -> dict:
    """Apa yang akan terjadi kalau berkas ini diimpor. Tidak menyimpan apa pun."""
    isi = await _baca_berkas(request)
    try:
        return await run_in_threadpool(impor.periksa, isi, nama_berkas=nama)
    except OperatorError as exc:
        raise _impor_ditolak(exc) from exc


@router.post("/api/console/dev/riwayat/impor", status_code=201)
async def dev_impor(
    request: Request,
    impor: Impor,
    operator: Support,
    nama: str = Query("", max_length=200),
    sidik: str = Query("", max_length=64),
) -> dict:
    """Simpan berkas yang SAMA dengan yang diperiksa (`sidik`). Ditolak utuh kalau
    ada satu baris salah; janjang hari ini dan sesudahnya tidak diimpor."""
    isi = await _baca_berkas(request)
    try:
        batch = await run_in_threadpool(
            impor.impor, isi, nama_berkas=nama, sidik=sidik, oleh=operator["email"]
        )
    except OperatorError as exc:
        raise _impor_ditolak(exc) from exc
    return {"batch": batch}


@router.get("/api/console/dev/riwayat/impor")
def dev_impor_daftar(impor: Impor, operator: Support) -> dict:
    """Dua puluh impor terakhir, yang terbaru dulu."""
    return impor.daftar()


@router.post("/api/console/dev/riwayat/impor/{batch_id}/batal")
def dev_impor_batal(batch_id: str, impor: Impor, operator: Support) -> dict:
    """Hapus semua janjang satu impor. Truk yang dibuatnya tetap ada."""
    try:
        return {"batch": impor.batalkan(batch_id, oleh=operator["email"])}
    except OperatorError as exc:
        raise _impor_ditolak(exc) from exc


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
    # Sisa penjaga ketik yang dicabut 2026-09-24 — tetap diterima (tanpa
    # diperiksa) supaya konsol yang belum dimuat ulang tidak mendadak 422.
    konfirmasi: Annotated[str, Body()] = "",
) -> dict:
    """The only lane in this whole console that moves physical hardware.

    Two guards: refused while the line is processing a truck (409, checked on
    the line — see DevService.plc_fire), and every attempt — fired or refused —
    leaves a WARNING row in event_log.
    """
    try:
        return await dev.plc_fire(
            line_code=line_code,
            coil=coil,
            konfirmasi=konfirmasi,
            operator_email=operator["email"],
        )
    except PlcSibuk as exc:
        raise _operator_error(409, exc) from exc
    except CoilTidakDikenal as exc:
        raise _operator_error(422, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc
    except ValueError as exc:
        # Must come AFTER CoilTidakDikenal above — it is ALSO a ValueError
        # (via OperatorError, ValueError), and a bare catch placed first would
        # swallow it into the wrong status code.
        raise _operator_error(404, exc) from exc
