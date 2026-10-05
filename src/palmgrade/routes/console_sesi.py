"""Sliding session (batch 5.7). Included by `routes/console.py`.

A module of its own because `routes/console.py` stays under 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). Included right after `/me`, so `console.router` lists
the session lanes together (`tests/unit/test_console_router_peta.py`).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from ..domain.operator_auth import SESSION_TTL_S
from ..domain.operator_error import BELUM_MASUK, OperatorError
from .console_deps import SESSION_COOKIE, Auth, Operator, _operator_error

sesi_router = APIRouter(tags=["console"])


def pasang_cookie_sesi(response: Response, token: str) -> None:
    """The session cookie, with the full lifetime from now. Sent at sign-in and on every
    renew: a cookie left with its first lifetime would be dropped by the browser while the
    server still holds the session."""
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


@sesi_router.post("/api/console/session/renew")
async def renew_session(
    auth: Auth, operator: Operator, response: Response,
    konsol_sesi: Annotated[str | None, Cookie()] = None,
) -> dict:
    """The operator touched the screen: the session runs 12 h from now (batch 5.7).

    The screen sends this for taps and keys, never for its own polls, so a screen left
    alone still signs itself out. `Operator` has already refused an ended session with
    401 `belum_masuk`; the second check covers a session that ends between the two.
    """
    hasil = auth.renew(konsol_sesi)
    if hasil is None:
        raise _operator_error(401, OperatorError(BELUM_MASUK, "belum masuk atau sesi habis"))
    pasang_cookie_sesi(response, konsol_sesi)
    return hasil
