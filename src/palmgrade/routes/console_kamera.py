"""Reconnect camera button on every line card (2026-10-04) and the support camera settings read (2026-10-05).

A module of its own because `routes/console.py` stays under 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). Included right after the piston route, so
`console.router` lists it with the other line actions (`tests/unit/test_console_router_peta.py`).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..integrations.notifications.line_client import KameraTanpaSambungUlang, LineUnavailable
from ..services.sambung_ulang_kamera import SambungUlangKamera
from ..services.setelan_kamera_konsol import SetelanKameraKonsol
from .console_deps import Operator, Service, Support, _operator_error

kamera_router = APIRouter(tags=["console"])


def get_sambung_ulang_kamera(service: Service) -> SambungUlangKamera:
    """The same lines and `LineClient` as the console service, so one override covers both."""
    return SambungUlangKamera(service.lines, service.line_client)


Kamera = Annotated[SambungUlangKamera, Depends(get_sambung_ulang_kamera)]


@kamera_router.post("/api/console/lines/{line_code}/reconnect-camera", status_code=202)
async def reconnect_camera(line_code: str, kamera: Kamera, operator: Operator) -> dict:
    """The spare for when the line's own automatic reconnect does not bring the camera
    back (user 2026-10-04). Every account (`require_operator`); recorded against whoever
    is signed in.

    `async` on purpose (rule 30): it touches no SQLite and only waits on the line, which
    answers before it touches the camera. No body: the line comes from the path, the name
    from the session.
    """
    try:
        return await kamera.minta(line_code, oleh=operator["full_name"] or operator["email"])
    except KameraTanpaSambungUlang as exc:
        raise _operator_error(409, exc) from exc
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc


def get_setelan_kamera(service: Service) -> SetelanKameraKonsol:
    """Same lines and `LineClient` as the console service, so one test override covers both."""
    return SetelanKameraKonsol(service.lines, service.line_client)


SetelanKamera = Annotated[SetelanKameraKonsol, Depends(get_setelan_kamera)]


@kamera_router.get("/api/console/dev/camera-settings")
async def dev_camera_settings(setelan: SetelanKamera, operator: Support) -> dict:
    """Camera settings of every line for the Setelan Kamera screen, support only (spec §3.2).

    `async` on purpose (rule 30): no SQLite, it only waits on the lines.
    """
    return await setelan.baca_semua()
