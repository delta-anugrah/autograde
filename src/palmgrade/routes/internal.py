from __future__ import annotations

import logging
import os
import threading
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from ..controllers.internal_controller import (
    line_status,
    manual_reject_command,
    piston_command,
    plc_coil_command,
    plc_state,
    sync_assignment,
)
from ..core.config import Settings
from ..core.dependencies import (
    get_capture_service,
    get_outbox_store,
    get_runtime_state,
    get_settings,
)
from ..domain.setelan_grading import bersihkan_setelan
from ..domain.setelan_rekam import SetelanRekamTidakSah, bersihkan_setelan_rekam
from ..integrations.outbox.outbox_store import OutboxStore
from ..schemas.internal_schema import (
    AssignmentSyncRequest,
    AssignmentSyncResponse,
    LineStatusResponse,
    ManualRejectCommandRequest,
    ManualRejectCommandResponse,
    OutboxRequeueResponse,
    PistonCommandRequest,
    PlcCoilCommandRequest,
    PlcCoilCommandResponse,
    PlcStateResponse,
    RestartResponse,
    SetelanGradingRequest,
    SetelanGradingResponse,
)
from ..services.capture_service import CaptureService
from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)


async def _verify_internal_secret(
    x_internal_secret: Annotated[str | None, Header()] = None,
) -> None:
    settings = get_settings()
    if x_internal_secret != settings.internal_secret:
        raise HTTPException(status_code=401, detail="Invalid internal secret")


router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(_verify_internal_secret)],
)


@router.post("/assignment", response_model=AssignmentSyncResponse)
async def assignment_sync(
    request: AssignmentSyncRequest,
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
) -> AssignmentSyncResponse:
    return await sync_assignment(request, state)


@router.post("/setelan", response_model=SetelanGradingResponse)
async def setelan_grading(
    request: SetelanGradingRequest,
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SetelanGradingResponse:
    """Timpa CONF_THRESHOLD/MINIMUM_SIZE line ini tanpa restart.

    Disimpan di `RuntimeState`, bukan di `Settings` (yang `frozen=True` dengan
    sengaja). Hilang kalau container dibuat ulang — itu disengaja: konsol yang
    memegang nilai sebenarnya dan mengirimnya lagi saat line kembali online,
    jadi tidak ada dua sumber kebenaran yang bisa berbeda diam-diam.
    """
    bersih = bersihkan_setelan(request.model_dump())
    state.conf_threshold_override = bersih["conf_threshold"]
    state.minimum_size_override = bersih["minimum_size"]
    state.garis_capture_override = bersih["garis_capture"]
    state.sumbu_garis_override = bersih["sumbu_garis"]
    state.mode_dev_override = bersih["mode_dev"]
    logger.warning(
        "Setelan grading diubah dari konsol: conf=%s minimum_size=%s garis=%s sumbu=%s "
        "(sebelumnya env conf=%s size=%s garis=%s sumbu=%s)",
        bersih["conf_threshold"], bersih["minimum_size"], bersih["garis_capture"],
        bersih["sumbu_garis"],
        settings.conf_threshold, settings.minimum_size, settings.garis_capture,
        settings.sumbu_garis,
    )
    return SetelanGradingResponse(**bersih, sumber="konsol")


@router.get("/setelan", response_model=SetelanGradingResponse)
async def setelan_grading_aktif(
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SetelanGradingResponse:
    """Yang BENAR-BENAR dipakai line ini sekarang, bukan yang ada di `.env`."""
    ditimpa = state.conf_threshold_override is not None
    return SetelanGradingResponse(
        conf_threshold=state.conf_threshold_override
        if ditimpa else settings.conf_threshold,
        minimum_size=state.minimum_size_override
        if state.minimum_size_override is not None else settings.minimum_size,
        garis_capture=state.garis_capture_override
        if state.garis_capture_override is not None else settings.garis_capture,
        sumbu_garis=state.sumbu_garis_override
        if state.sumbu_garis_override is not None else settings.sumbu_garis,
        mode_dev=state.mode_dev_override
        if state.mode_dev_override is not None else settings.mode_dev,
        sumber="konsol" if ditimpa else "env",
    )


@router.post("/manual-reject", response_model=ManualRejectCommandResponse)
async def manual_reject(
    request: ManualRejectCommandRequest,
    service: Annotated[CaptureService, Depends(get_capture_service)],
) -> ManualRejectCommandResponse:
    return await manual_reject_command(request, service)


@router.post("/outbox/requeue", response_model=OutboxRequeueResponse)
async def outbox_requeue(
    outbox: Annotated[OutboxStore, Depends(get_outbox_store)],
) -> OutboxRequeueResponse:
    # Move dead-letter events (status='failed') back to 'pending' so
    # OutboxRetryWorker tries sending them again. Used after the API recovers
    # from a long outage. Safe to repeat (idempotent when nothing has failed).
    return OutboxRequeueResponse(requeued=outbox.requeue_failed())


@router.post("/piston", response_model=LineStatusResponse)
async def piston(
    request: PistonCommandRequest,
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
) -> LineStatusResponse:
    return await piston_command(request, state)


@router.get("/status", response_model=LineStatusResponse)
async def line_status_endpoint(
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
) -> LineStatusResponse:
    return await line_status(state)


@router.get("/plc", response_model=PlcStateResponse)
async def plc_state_endpoint() -> PlcStateResponse:
    return await plc_state()


@router.post("/plc/coil", response_model=PlcCoilCommandResponse)
async def plc_coil(
    request: PlcCoilCommandRequest,
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
) -> PlcCoilCommandResponse:
    return await plc_coil_command(request, state)


#: Jeda antara menjawab dan keluar. Cukup bagi respons untuk sampai ke konsol
#: melalui loop event, tidak cukup lama untuk membuat layar terasa menggantung.
_JEDA_KELUAR_DETIK = 1.0


def _jadwalkan_keluar(jeda: float) -> None:
    """Keluar `jeda` detik dari sekarang, di thread terpisah.

    `os._exit` dan bukan `sys.exit`: yang dituju adalah container berhenti
    supaya `restart: unless-stopped` menyalakannya lagi dengan environment yang
    Compose baca ulang. `sys.exit` dari thread non-utama hanya menghentikan
    thread itu — proses tetap hidup dan setelan baru tidak pernah berlaku,
    tanpa satu pun galat yang terlihat.
    """
    def keluar() -> None:
        time.sleep(jeda)
        # Tidak menyebut "Docker": di pabrik memang `restart: unless-stopped`
        # yang menyalakan ulang, tapi jalur native dinyalakan loop `make line`.
        # Pesan yang menyebut Docker di terminal `make line` membuat orang
        # mencari container yang tidak ada.
        logger.warning("Keluar atas permintaan konsol — menunggu dinyalakan ulang")
        os._exit(0)  # noqa: SLF001 — disengaja, lihat docstring

    threading.Thread(target=keluar, daemon=True, name="restart").start()


@router.post("/restart", response_model=RestartResponse)
async def restart() -> RestartResponse:
    """Matikan diri supaya Docker menyalakan ulang dengan setelan baru.

    Dipanggil konsol sesudah `media.env` ditulis. Line membaca sumber kameranya
    dari environment saat boot, jadi setelan baru baru berlaku setelah proses
    ini benar-benar mati dan `restart: unless-stopped` membangunnya kembali.

    Menjawab lebih dulu, keluar belakangan: konsol yang melihat koneksi putus
    akan melaporkannya sebagai gagal padahal berhasil, dan support akan menekan
    Simpan lagi.
    """
    logger.warning("Permintaan restart diterima dari konsol")
    _jadwalkan_keluar(_JEDA_KELUAR_DETIK)
    return RestartResponse(status="restarting", jeda_detik=_JEDA_KELUAR_DETIK)


# ── rekam video developer ───────────────────────────────────────────────────
#
# Konsol yang memegang tombolnya; line yang merekam. Setelan dikirim konsol tiap
# kali mulai dan TIDAK disimpan di sini — itu yang membuat "restart container =
# rekaman mati" (keputusan 2026-09-22) jadi sifat, bukan sesuatu yang harus
# dijaga kode tambahan.

_recorder_lock = threading.Lock()


def _recorder(state: RuntimeState, settings: Settings):
    """Recorder line ini, dibuat saat pertama dibutuhkan.

    Dibuat malas supaya line yang tidak pernah merekam tidak menyentuh folder
    `videos/` sama sekali. Di balik lock: dua permintaan yang datang bersamaan
    akan membuat dua recorder, dan yang kedua menimpa yang pertama di
    `state.video_recorder` — rekaman pertama jalan terus tanpa ada yang bisa
    menghentikannya.
    """
    from ..services.video_recorder import VideoRecorder

    with _recorder_lock:
        if state.video_recorder is None:
            state.video_recorder = VideoRecorder(
                videos_dir=settings.videos_dir,
                line_code=settings.line_code,
                disk_min_free_gb=settings.upload_disk_min_free_gb,
            )
        return state.video_recorder


@router.post("/rekam/mulai")
async def rekam_mulai(
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: dict | None = None,
) -> dict:
    """Mulai merekam line ini dengan setelan yang dikirim konsol."""
    from ..services.video_recorder import DiskMepet, RekamSedangJalan

    try:
        bersih = bersihkan_setelan_rekam(request or {})
    except SetelanRekamTidakSah as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return _recorder(state, settings).mulai(bersih)
    except RekamSedangJalan as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DiskMepet as exc:
        # 507 Insufficient Storage: bukan salah pemanggil, dan bukan kerusakan.
        raise HTTPException(status_code=507, detail=str(exc)) from exc


@router.post("/rekam/stop")
async def rekam_stop(
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    from ..services.video_recorder import RekamTidakJalan

    try:
        return _recorder(state, settings).stop()
    except RekamTidakJalan as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/rekam/status")
async def rekam_status(
    state: Annotated[RuntimeState, Depends(get_runtime_state)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    return _recorder(state, settings).status()
