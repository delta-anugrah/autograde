"""Mount `/captures`: foto saja, dan di konsol hanya untuk yang sudah masuk.

`StaticTanpaDb` dipakai line (tanpa konsep sesi; konsumen lama di PC lain) dan
konsol. `CapturesBersesi` menambah pemeriksaan sesi per permintaan untuk konsol
(batch 1.3): mount lama berada di luar pemeriksaan sesi, jadi semua foto bukti
terbaca siapa pun di LAN pabrik. Sesinya diperiksa `AuthService` yang sama
dengan lane operator, disuntik supaya modul ini tidak mengenal konsol.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

from ..domain.berkas_captures import boleh_disajikan
from ..domain.operator_error import BELUM_MASUK, OperatorError


class _Sesi(Protocol):
    def current(self, token: str | None) -> dict[str, Any] | None: ...


class StaticTanpaDb(StaticFiles):
    """`StaticFiles` yang menjawab 404 untuk basis data dan berkas tersembunyi."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if not boleh_disajikan(path):
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


class CapturesBersesi(StaticTanpaDb):
    def __init__(self, *, directory: str, sesi: Callable[[], _Sesi], cookie: str) -> None:
        super().__init__(directory=directory)
        self._sesi = sesi
        self._cookie = cookie

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = Request(scope).cookies.get(self._cookie)
        if await run_in_threadpool(self._sesi().current, token) is None:
            detail = OperatorError(BELUM_MASUK, "belum masuk atau sesi habis").as_detail()
            await JSONResponse({"detail": detail}, status_code=401)(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
