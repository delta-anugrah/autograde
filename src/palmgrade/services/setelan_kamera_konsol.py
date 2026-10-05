"""Console side of the camera settings screen (tab Line, Setelan Kamera, spec §3.2).

Its own module because `services/console_service.py` stays under 1,000 lines. Holds the same line list and
`LineClient` as `ConsoleService` (`routes/console_kamera.get_setelan_kamera`), like `SambungUlangKamera`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from ..core.config import LineEndpoint
from ..domain.line_tak_terbaca import SEBAB_LAIN
from ..domain.operator_error import OperatorError
from ..domain.setelan_kamera import sebab_setelan_tak_terbaca
from ..integrations.notifications.line_client import LineClient

logger = logging.getLogger(__name__)


def _sebab(exc: BaseException) -> str:
    if isinstance(exc, OperatorError):
        return sebab_setelan_tak_terbaca(exc.code, exc.params.get("status"))
    return SEBAB_LAIN


class SetelanKameraKonsol:
    def __init__(self, lines: Sequence[LineEndpoint], line_client: LineClient) -> None:
        self._lines = tuple(lines)
        self._line_client = line_client

    async def baca_semua(self) -> dict[str, Any]:
        """Every line at once; one line that fails never empties the other cards (like `DevService.diagnostics`)."""
        hasil = await asyncio.gather(
            *(self._line_client.camera_settings(line) for line in self._lines), return_exceptions=True
        )
        lines: dict[str, Any] = {}
        for line, entry in zip(self._lines, hasil, strict=True):
            if isinstance(entry, BaseException):
                # INFO, not WARNING: a support screen read on demand; the Log tab already carries line faults.
                logger.info("Camera settings of %s not read: %s", line.line_code, entry)
                lines[line.line_code] = {"terjangkau": False, "sebab_kode": _sebab(entry)}
            else:
                lines[line.line_code] = {"terjangkau": True, **entry}
        return {"lines": lines}
