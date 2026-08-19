from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .manager import LicenseManager

logger = logging.getLogger(__name__)

# Paths yang selalu diizinkan tanpa cek license. /health tetap terbuka supaya
# operator dan watchdog masih bisa melihat kenapa mesin berhenti.
_ALWAYS_ALLOWED = {"/health", "/jwks.json", "/docs", "/openapi.json", "/redoc", "/captures", "/api/video_feed"}


class LicenseGuardMiddleware(BaseHTTPMiddleware):
    """Gate HTTP. Ini SETENGAH penjagaan saja — grading AI jalan di thread
    background yang tidak lewat sini, jadi gate yang sesungguhnya ada di
    FrameProcessingWorker. Tanpa itu, dashboard mati tapi kamera tetap
    menyortir buah."""

    def __init__(self, app, manager: LicenseManager) -> None:
        super().__init__(app)
        self._manager = manager

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if any(path.startswith(p) for p in _ALWAYS_ALLOWED):
            return await call_next(request)

        try:
            effective = await self._manager.get_effective_license()
        except Exception as exc:
            logger.error("License check failed: %s", exc)
            return JSONResponse(
                status_code=503,
                content={"error": "LICENSE_CHECK_FAILED", "reason": str(exc)},
            )

        if effective.is_expired:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "LICENSE_INVALID",
                    "status": effective.status,
                    "reason": effective.reason,
                },
            )

        response = await call_next(request)

        if effective.warning:
            response.headers["x-license-warning-code"] = effective.warning.code
            response.headers["x-license-warning-message"] = effective.warning.message
            response.headers["x-license-warning-days-remaining"] = str(effective.warning.days_remaining)

        return response
