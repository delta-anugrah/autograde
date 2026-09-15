"""Perintah konsol → line kamera (§4 rencana PalmOS).

Arahnya sama persis dengan palmgrade-api → vision, jadi kontraknya dipertahankan
apa adanya: header `x-internal-secret` dan body yang sama, supaya `routes/internal.py`
di line tidak perlu diubah sama sekali.

Dipisah dari `ConsoleService` karena ini satu-satunya bagian yang tahu soal HTTP:
service cukup tahu "suruh line ini menugaskan truk", tidak tahu URL, header,
timeout, atau bentuk error httpx. Efek sampingnya yang paling berguna: test bisa
menukar satu kolaborator, bukan menambal method privat milik service.

Pola & lokasinya mengikuti `webhook_client.py` di folder yang sama.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ...core.config import LineEndpoint, Settings
from ...domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB, OperatorError

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0


class LineUnavailable(OperatorError, RuntimeError):
    """Line kamera tidak menjawab — operator harus lihat ini, bukan diam."""


class LineClient:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport  # tests swap the network, like ErpClient

    async def assign_truck(
        self,
        line: LineEndpoint,
        *,
        assignment_id: str,
        truck_id: str,
        assigned_at: str,
        ffb_source: str | None = None,
    ) -> None:
        await self._post(
            line,
            "/internal/assignment",
            {
                "machine_id": line.machine_id,
                "assignment_id": assignment_id,
                "truck_id": truck_id,
                "assigned_at": assigned_at,
                # Line lama mengabaikan field asing (pydantic extra=ignore), jadi
                # aman dikirim ke image yang belum mengenalnya.
                "ffb_source": ffb_source,
            },
        )

    async def manual_reject(
        self, line: LineEndpoint, *, assignment_id: str, requested_by: str, requested_at: str
    ) -> None:
        await self._post(
            line,
            "/internal/manual-reject",
            {
                "machine_id": line.machine_id,
                "assignment_id": assignment_id,
                "requested_by": requested_by,
                "requested_at": requested_at,
            },
        )

    async def set_piston(
        self, line: LineEndpoint, *, open: bool, requested_by: str, requested_at: str
    ) -> None:
        await self._post(
            line,
            "/internal/piston",
            {
                "machine_id": line.machine_id,
                "open": open,
                "requested_by": requested_by,
                "requested_at": requested_at,
            },
        )

    async def status(self, line: LineEndpoint) -> dict[str, Any]:
        """Dipanggil tiap detik oleh LineStatusWorker, jadi timeoutnya pendek:
        layar operator tidak boleh ikut menunggu line yang sekarat."""
        url = f"{self._settings.console_line_host}:{line.port}/internal/status"
        try:
            async with httpx.AsyncClient(timeout=1.5, transport=self._transport) as client:
                res = await client.get(
                    url, headers={"x-internal-secret": self._settings.internal_secret}
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} tidak menjawab: {exc}", line=line.name
            ) from exc

    async def _post(self, line: LineEndpoint, path: str, body: dict[str, Any]) -> None:
        url = f"{self._settings.console_line_host}:{line.port}{path}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.post(
                    url,
                    json=body,
                    headers={"x-internal-secret": self._settings.internal_secret},
                )
        except httpx.HTTPError as exc:
            # The screen shows a translated sentence; the httpx cause lives in the log.
            logger.warning("Perintah %s ke %s gagal: %s", path, line.line_code, exc)
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} tidak menjawab: {exc}", line=line.name
            ) from exc
        if res.status_code >= 400:
            logger.warning(
                "Perintah %s ditolak %s: HTTP %s %s",
                path, line.line_code, res.status_code, res.text[:200],
            )
            raise LineUnavailable(
                LINE_MENOLAK,
                f"{line.line_code} menolak: HTTP {res.status_code} {res.text[:200]}",
                line=line.name,
                status=res.status_code,
            )
        logger.info("Perintah %s diterima %s", path, line.line_code)
