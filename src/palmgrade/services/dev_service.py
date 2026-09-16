"""Flow behind the developer screens (support role only).

The value is not new data — `/health/detail`, the ERP queue, settings are all
already logged today. It is that they finally get a screen, instead of only
being readable with `curl`.

Flow only: HTTP to the lines lives in `LineClient`, persistence in
`ErpOutboxStore` and `LogStore`. This class just asks them and shapes the
answer for the screen.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..core.config import LineEndpoint, Settings
from ..domain.operator_error import (
    COIL_TIDAK_DIKENAL,
    KONFIRMASI_KURANG,
    LINE_TIDAK_DIKENAL,
    PLC_SIBUK,
    InvalidInput,
    OperatorError,
)
from ..integrations.erp.outbox_store import ErpOutboxStore
from ..integrations.notifications.line_client import LineClient, LinePlcTolak, LineUnavailable
from ..repositories.log_repository import LogStore

logger = logging.getLogger(__name__)

# Purge at most this often. A worker of its own would be one more thread a
# factory PC has to pay for, for a table that grows a few hundred rows a day.
_PURGE_INTERVAL_S = 3600.0

# Typed exactly, not just "non-empty": the PLC test screen is the only one
# that moves physical hardware, and a stray character landing in the field
# (autocomplete, a brushed key) must not read as a deliberate confirmation.
# Value is a console.html contract ("Type UJI to continue") — do not change it.
_PLC_TEST_CONFIRMATION = "UJI"


class KonfirmasiKurang(OperatorError, ValueError):
    """Typed confirmation did not match — the coil must not fire."""

    def __init__(self, message: str) -> None:
        super().__init__(KONFIRMASI_KURANG, message)


class PlcSibuk(OperatorError, RuntimeError):
    """Line is busy processing a truck — the coil must not fire."""

    def __init__(self, message: str) -> None:
        super().__init__(PLC_SIBUK, message)


class CoilTidakDikenal(OperatorError, ValueError):
    """Line rejected this coil number (not part of `testable_coils`)."""

    def __init__(self, message: str) -> None:
        super().__init__(COIL_TIDAK_DIKENAL, message)


class DevService:
    def __init__(
        self,
        log_store: LogStore,
        *,
        line_client: LineClient | None = None,
        lines: tuple[LineEndpoint, ...] = (),
        erp_outbox: ErpOutboxStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._log = log_store
        self._last_purge = 0.0
        self._line_client = line_client
        self._lines = lines
        self._erp_outbox = erp_outbox
        self._settings = settings

    def log(
        self, *, level: str | None, search: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        self._purge_periodically()
        return self._log.read(level=level, search=search, limit=limit, offset=offset)

    def _purge_periodically(self, *, now: float | None = None) -> None:
        """Sweep expired rows, tied to a read rather than its own timer."""
        current = now if now is not None else time.time()
        if current - self._last_purge < _PURGE_INTERVAL_S:
            return
        self._last_purge = current
        self._log.purge_expired(now=current)

    async def diagnostics(self) -> dict[str, Any]:
        """`/health/detail` from every line, gathered concurrently.

        A line that does not answer is reported `terjangkau: False` with the
        reason, never raised — a dead line is the thing this screen most
        needs to show, and one dead line must not empty it for the other two.
        """
        results = await asyncio.gather(
            *(self._one_line(line) for line in self._lines), return_exceptions=True
        )
        lines: dict[str, Any] = {}
        for line, entry in zip(self._lines, results, strict=True):
            # Any exception (LineUnavailable or otherwise) reads as unreachable —
            # a bug in one line's fetch must not take the other two cards down too.
            if isinstance(entry, BaseException):
                lines[line.line_code] = {"terjangkau": False, "sebab": str(entry)}
            else:
                lines[line.line_code] = {"terjangkau": True, **entry}
        return {"lines": lines}

    async def _one_line(self, line: LineEndpoint) -> dict[str, Any]:
        return await self._line_client.health_detail(line)

    def queue(self) -> dict[str, Any]:
        return {
            "pending": self._erp_outbox.pending_count(),
            "gagal": self._erp_outbox.failed_count(),
            "items": self._erp_outbox.failed_rows(limit=50),
        }

    def resend(self) -> dict[str, Any]:
        return {"dikirim_ulang": self._erp_outbox.requeue_failed()}

    async def plc_read(self, line_code: str) -> dict[str, Any]:
        """DI snapshot + testable coils for one line. Read-only — safe to open anytime."""
        line = self._require_line(line_code)
        return await self._line_client.plc_state(line)

    async def plc_fire(
        self, *, line_code: str, coil: int, konfirmasi: str, operator_email: str
    ) -> dict[str, Any]:
        """Fire one PLC coil on `line_code` to tell a wiring fault from a program
        fault at commissioning — the only console action that moves real hardware.

        Three guards, all mandatory: typed confirmation (not a click, which a
        touchscreen can register from a brush), refused while that line is
        processing a truck (checked on the line itself — this process does not
        own its RuntimeState), and every attempt logged WARNING regardless of
        outcome, so an incident always has a trail naming who pressed what.
        """
        line = self._require_line(line_code)
        if konfirmasi.strip() != _PLC_TEST_CONFIRMATION:
            raise KonfirmasiKurang(f"type '{_PLC_TEST_CONFIRMATION}' before firing the coil")
        try:
            result = await self._line_client.plc_coil(
                line, coil=coil, requested_by=operator_email
            )
        except LinePlcTolak as exc:
            # Every attempt is logged, hit or refused: a coil that was REFUSED is
            # still an event support needs to see in the trail, same as one fired.
            # logger.warning(), not LogStore.write() directly, so this goes through
            # the same SqliteLogHandler as everything else in log_kejadian —
            # that is what applies redact() before the row settles on disk.
            logger.warning(
                "PLC TEST: %s fired coil %s on %s — rejected by line: %s",
                operator_email, coil, line_code, exc,
            )
            if exc.status_code == 409:
                raise PlcSibuk("line is processing a truck") from exc
            if exc.status_code == 422:
                raise CoilTidakDikenal(f"coil {coil} is not known") from exc
            raise
        except LineUnavailable as exc:
            # An unreachable line is the ORDINARY state while a mill is being
            # commissioned or is already broken — exactly when this button gets
            # pressed, and exactly when the trail matters most. LineClient logs
            # its own line (line_client.py) for the network story, but that log
            # line has no idea who the operator is — this one does.
            logger.warning(
                "PLC TEST: %s fired coil %s on %s — line unreachable: %s",
                operator_email, coil, line_code, exc,
            )
            raise
        logger.warning(
            "PLC TEST: %s fired coil %s on %s (fired=%s)",
            operator_email, coil, line_code, result.get("fired"),
        )
        return {"line_code": line_code, **result}

    def _require_line(self, line_code: str) -> LineEndpoint:
        for line in self._lines:
            if line.line_code == line_code:
                return line
        raise InvalidInput(LINE_TIDAK_DIKENAL, f"unknown line: {line_code}", line=line_code)

    def version(self) -> dict[str, Any]:
        """Version, machine id, environment, licence state.

        Never the webhook secret, the ERP key, or a password hash — this
        screen is read over AnyDesk, not a place for credentials.
        """
        return {
            "versi": self._settings.app_version,
            "machine_id": self._settings.machine_id,
            "environment": self._settings.environment,
            "lisensi": {
                "aktif": self._settings.lic_enabled,
                "token_terpasang": bool(self._settings.lic_token),
            },
        }
