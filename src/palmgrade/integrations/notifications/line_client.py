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


class LinePlcTolak(RuntimeError):
    """Line answered but refused the PLC coil command (409 busy, 422 unknown coil).

    Kept separate from `LineUnavailable`: those two codes are the dev screen's
    own safety guards echoed back from the line, not "the line is down" —
    DevService needs the real status_code to answer the console the same way.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


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

    async def plc_state(self, line: LineEndpoint) -> dict[str, Any]:
        """DI snapshot + testable coils for the commissioning test screen.

        Read-only lane; same short timeout as `status()` — this backs a
        polling screen, not a once-a-shift diagnostic read.
        """
        url = f"{self._settings.console_line_host}:{line.port}/internal/plc"
        try:
            async with httpx.AsyncClient(timeout=2.0, transport=self._transport) as client:
                res = await client.get(
                    url, headers={"x-internal-secret": self._settings.internal_secret}
                )
                res.raise_for_status()
                return res.json()
        except httpx.HTTPError as exc:
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} tidak menjawab: {exc}", line=line.name
            ) from exc

    async def plc_coil(self, line: LineEndpoint, *, coil: int, requested_by: str) -> dict[str, Any]:
        """Fire one PLC coil on `line` for a wiring test. Raises on 4xx/5xx —
        the caller (DevService) must see the reason, not a silent no-op."""
        url = f"{self._settings.console_line_host}:{line.port}/internal/plc/coil"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.post(
                    url,
                    json={"machine_id": line.machine_id, "coil": coil, "requested_by": requested_by},
                    headers={"x-internal-secret": self._settings.internal_secret},
                )
        except httpx.HTTPError as exc:
            logger.warning("Uji PLC coil %s ke %s gagal: %s", coil, line.line_code, exc)
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB, f"{line.line_code} tidak menjawab: {exc}", line=line.name
            ) from exc
        if res.status_code >= 400:
            # 409 busy / 422 unknown coil are the line's own safety answers, not
            # "unreachable" — raised distinctly so DevService can echo the same
            # status back to the console instead of collapsing both into 502.
            raise LinePlcTolak(res.status_code, res.text[:200])
        return res.json()

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

    async def health_detail(self, line: LineEndpoint) -> dict[str, Any]:
        """Full `/health/detail` for the support diagnostics screen.

        Longer timeout than `status()`: this is a support-only read, not the
        once-a-second path, so it can afford to wait a little longer on a
        struggling line instead of flagging it unreachable too eagerly.
        """
        url = f"{self._settings.console_line_host}:{line.port}/health/detail"
        try:
            async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
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
