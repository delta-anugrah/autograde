"""`POST /internal/camera/reconnect` and `GET /internal/camera/settings` on the LINE (2026-10-04, 2026-10-05).

The route never touches the camera: the SDK is not thread safe, and the capture thread
is the only one that may open or close it, under `state.lock` (rule 3). It raises a flag
on `RuntimeState` and answers 202 at once; `FrameCaptureWorker` reconnects on its next
turn, with no backoff wait. The card shows the result through the usual online and
frame states.

Assembled through `buat_router()` with injected dependencies, like
`routes/internal_bahaya.py`: `routes/internal.py` pulls in torch, and this lane runs in CI.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from ..core.config import Settings
from ..domain.operator_error import KAMERA_TANPA_SAMBUNG_ULANG, KAMERA_TANPA_SETELAN, KAMERA_TIDAK_MENJAWAB
from ..domain.setelan_kamera import baris_setelan
from ..integrations.camera.base import CameraSource
from ..integrations.camera.berkas_fitur import berkas_tersimpan
from ..schemas.internal_schema import CameraReconnectRequest
from ..workers.perintah_kamera import BATAS_PERINTAH_KAMERA_DETIK, KameraTidakMenjawab
from ..workers.runtime_state import RuntimeState
from .penjaga_rahasia import penjaga_internal

logger = logging.getLogger(__name__)

# 409 `KAMERA_TANPA_SAMBUNG_ULANG` for a video file or photo source: there is no camera to
# reconnect. The console forwards the code; the screen words it.
__all__ = ["KAMERA_TANPA_SAMBUNG_ULANG", "buat_router"]


def buat_router(
    *,
    settings: Callable[[], Settings],
    state: Callable[[], RuntimeState],
    kamera: Callable[[], CameraSource],
) -> APIRouter:
    """Router `/internal/camera/...` for one line process, behind `INTERNAL_SECRET`."""
    router = APIRouter(
        prefix="/internal",
        tags=["internal"],
        dependencies=[Depends(penjaga_internal(settings))],
    )

    @router.post("/camera/reconnect", status_code=202)
    async def sambung_ulang_kamera(request: CameraReconnectRequest) -> dict[str, str]:
        if not kamera().supports_reconnect:
            raise HTTPException(
                status_code=409,
                detail={"kode": KAMERA_TANPA_SAMBUNG_ULANG, "pesan": "sumber gambar line ini bukan kamera"},
            )
        logger.info("Manual camera reconnect requested by %s", request.requested_by)
        state().minta_sambung_ulang_kamera(request.requested_by)
        return {"status": "requested"}

    @router.get("/camera/settings")
    def setelan_kamera() -> dict:
        """The camera settings as the camera reports them now (spec §3.2).

        A plain `def` on purpose: it waits on the capture thread (`state.perintah_kamera`), and FastAPI runs a
        sync route in its thread pool instead of blocking the event loop.
        """
        kamera_ini = kamera()
        if not kamera_ini.punya_setelan:
            raise HTTPException(
                status_code=409,
                detail={"kode": KAMERA_TANPA_SETELAN, "pesan": "sumber gambar line ini bukan kamera Hikrobot"},
            )
        st = state()
        try:
            nilai = st.perintah_kamera.minta(kamera_ini.baca_setelan, batas_detik=BATAS_PERINTAH_KAMERA_DETIK)
        except (KameraTidakMenjawab, RuntimeError) as exc:
            logger.info("Camera settings not read: %s", exc)
            raise HTTPException(
                status_code=503, detail={"kode": KAMERA_TIDAK_MENJAWAB, "pesan": "kamera tidak menjawab"}
            ) from exc
        if nilai and not any(n.didukung for n in nilai):
            # Every node refused = a camera that went silent (cable pulled, `connected` not yet cleared by the
            # capture thread), not a camera that supports nothing.
            logger.info("Camera settings not read: the camera refused every node")
            raise HTTPException(
                status_code=503, detail={"kode": KAMERA_TIDAK_MENJAWAB, "pesan": "kamera tidak menjawab"}
            )
        simpanan = berkas_tersimpan(settings().camera_setelan_dir, settings().line_code)
        return {
            "berkas_tersimpan": simpanan is not None and simpanan.is_file(),
            "berkas_fitur": st.berkas_fitur_aktif,
            "setelan": baris_setelan(nilai),
        }

    return router
