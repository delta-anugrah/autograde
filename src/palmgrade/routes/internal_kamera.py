"""`POST /internal/camera/reconnect` on the LINE: the reconnect camera button (2026-10-04).

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
from ..domain.operator_error import KAMERA_TANPA_SAMBUNG_ULANG
from ..integrations.camera.base import CameraSource
from ..schemas.internal_schema import CameraReconnectRequest
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

    return router
