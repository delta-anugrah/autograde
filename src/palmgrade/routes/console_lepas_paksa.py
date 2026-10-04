"""Lepas paksa on a line card (2026-10-04). Included by `routes/console.py`.

A module of its own because `routes/console.py` stays under 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). Included right after the release route, so
`console.router` lists the two releases together (`tests/unit/test_console_router_peta.py`).
"""
from __future__ import annotations

from fastapi import APIRouter

from ..integrations.notifications.line_client import LineUnavailable
from .console_deps import Operator, Service, _operator_error

lepas_paksa_router = APIRouter(tags=["console"])


@lepas_paksa_router.post("/api/console/lines/{line_code}/force-release")
async def force_release(line_code: str, service: Service, operator: Operator) -> dict:
    """Release a truck from a line that does not answer (rule 13). Every account
    (`require_operator`), recorded against whoever is signed in.

    The server decides, not the screen: a line that answers is released normally
    (`paksa: false`), a line that answers with a refusal is 502 with its code, and only a
    line that gives no answer at all is cleared on the console alone (`paksa: true`).
    `async` on purpose (rule 30): it waits on the line, like Lepas.
    """
    nama, email = operator.get("full_name"), operator.get("email")
    oleh = f"{nama} ({email})" if nama and email and nama != email else (nama or email or "?")
    try:
        return await service.force_release(line_code, oleh=oleh)
    except ValueError as exc:
        raise _operator_error(404, exc) from exc
    except LineUnavailable as exc:
        raise _operator_error(502, exc) from exc
