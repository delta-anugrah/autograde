"""Console side of the reconnect camera button on every line card (2026-10-04).

Its own module because `services/console_service.py` stays under 1,000 lines
(`tests/unit/test_ukuran_berkas.py`). It holds the same line list and `LineClient` as
`ConsoleService` (`routes/console_kamera.get_sambung_ulang_kamera` hands them over), so
a test that overrides `get_console_service` reaches its own fake lines here too.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..core.config import LineEndpoint
from ..domain.operator_error import LINE_TIDAK_DIKENAL, InvalidInput
from ..integrations.notifications.line_client import LineClient

logger = logging.getLogger(__name__)


class SambungUlangKamera:
    def __init__(self, lines: Sequence[LineEndpoint], line_client: LineClient) -> None:
        self._by_code = {line.line_code: line for line in lines}
        self._line_client = line_client

    async def minta(self, line_code: str, *, oleh: str) -> dict[str, Any]:
        """Ask the line to reconnect its camera, in the name of whoever pressed the button.

        Logged BEFORE the call and as a WARNING, like the piston: grading on that line
        pauses for a few seconds, and the Log tab keeps only WARNING and ERROR, so this
        is the line that says who pressed it and when. Raises `InvalidInput` for an
        unknown line, and what `LineClient.reconnect_camera` raises.
        """
        line = self._by_code.get(line_code)
        if line is None:
            raise InvalidInput(LINE_TIDAK_DIKENAL, f"line tidak dikenal: {line_code}", line=line_code)
        logger.warning("Sambung ulang kamera %s diminta oleh %s", line_code, oleh)
        await self._line_client.reconnect_camera(line, requested_by=oleh)
        return {"line_code": line_code, "status": "requested"}
