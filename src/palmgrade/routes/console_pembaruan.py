"""Update now (batch 4.6, rule 38): operator AND support.

A module of its own because `routes/console.py` stays under 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). Included where the two routes used to sit, so
`console.router` lists them in the same order (`tests/unit/test_console_router_peta.py`).
The console only writes a marker; the host watcher installs. No Docker in here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from ..domain.operator_error import OperatorError
from ..domain.pembaruan import (
    PembaruanAdaTruk,
    PembaruanBelumTerpasang,
    PembaruanLepasGagal,
    line_bertruk,
)
from ..integrations.notifications.line_client import LineUnavailable
from ..schemas.console_schema import PasangBody
from ..services.console_service import ConsoleService
from .console_deps import Operator, Pembaruan, Service, _operator_error

logger = logging.getLogger(__name__)

pembaruan_router = APIRouter(tags=["console"])


@pembaruan_router.get("/api/console/update")
async def update_status(pembaruan: Pembaruan, operator: Operator) -> dict:
    return (await run_in_threadpool(pembaruan.keadaan)).as_dict()


@pembaruan_router.post("/api/console/update/install", status_code=202)
async def update_install(payload: PasangBody, service: Service, pembaruan: Pembaruan, operator: Operator) -> dict:
    target = payload.target or ""
    async with pembaruan.kunci:
        try:
            # Every other refusal first: nothing is released for an install that is refused anyway.
            await run_in_threadpool(pembaruan.periksa, target)
            # An assign still waiting for its line cannot be released yet: refuse as before.
            if pembaruan.line_sedang_ditugaskan():
                raise PembaruanAdaTruk(pembaruan.line_sedang_ditugaskan())
            dilepas = await _lepas_semua(service, target, operator["email"])
            hasil = await run_in_threadpool(pembaruan.pasang, target, [], operator["email"])
        except PembaruanBelumTerpasang as exc:
            raise _operator_error(503, exc) from exc
        except OperatorError as exc:
            raise _operator_error(409, exc) from exc
        except OSError as exc:
            # Folder mounted read-only or disk full: the marker never landed, nothing runs.
            raise _operator_error(500, exc) from exc
    return {**hasil, "dilepas": dilepas}


async def _lepas_semua(service: ConsoleService, target: str, oleh: str) -> list[dict]:
    """Release every truck the way the Release button does, minus filling the line again
    (`isi_line_otomatis` would take `pembaruan.kunci`, held here, and the line restarts anyway)."""
    assignments = await run_in_threadpool(service.assignments)
    dilepas: list[dict] = []
    for line in line_bertruk(assignments):
        plat = assignments[line].get("plate_number") or ""
        try:
            await service.release_truck(line)
        except (LineUnavailable, OperatorError) as exc:
            raise PembaruanLepasGagal(line) from exc
        logger.warning("Pembaruan %s: truk %s dilepas dari %s sebelum dipasang, oleh %s", target, plat, line, oleh)
        dilepas.append({"line_code": line, "plate_number": plat})
    return dilepas
