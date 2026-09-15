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
_BUANG_INTERVAL_S = 3600.0

# Typed exactly, not just "non-empty": the PLC test screen is the only one
# that moves physical hardware, and a stray character landing in the field
# (autocomplete, a brushed key) must not read as a deliberate confirmation.
_KONFIRMASI_UJI_PLC = "UJI"


class KonfirmasiKurang(OperatorError, ValueError):
    """Konfirmasi ketik belum sesuai — coil tidak boleh dipicu."""

    def __init__(self, message: str) -> None:
        super().__init__(KONFIRMASI_KURANG, message)


class PlcSibuk(OperatorError, RuntimeError):
    """Line sedang memproses truk — coil tidak boleh dipicu."""

    def __init__(self, message: str) -> None:
        super().__init__(PLC_SIBUK, message)


class CoilTidakDikenal(OperatorError, ValueError):
    """Line menolak nomor coil ini (bukan bagian dari `testable_coils`)."""

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
        self._buang_terakhir = 0.0
        self._line_client = line_client
        self._lines = lines
        self._erp_outbox = erp_outbox
        self._settings = settings

    def log(
        self, *, level: str | None, cari: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        self._buang_berkala()
        return self._log.baca(level=level, cari=cari, limit=limit, offset=offset)

    def _buang_berkala(self, *, now: float | None = None) -> None:
        """Sweep expired rows, tied to a read rather than its own timer."""
        sekarang = now if now is not None else time.time()
        if sekarang - self._buang_terakhir < _BUANG_INTERVAL_S:
            return
        self._buang_terakhir = sekarang
        self._log.buang_kedaluwarsa(now=sekarang)

    async def diagnostik(self) -> dict[str, Any]:
        """`/health/detail` from every line, gathered concurrently.

        A line that does not answer is reported `terjangkau: False` with the
        reason, never raised — a dead line is the thing this screen most
        needs to show, and one dead line must not empty it for the other two.
        """
        hasil = await asyncio.gather(
            *(self._satu_line(line) for line in self._lines), return_exceptions=True
        )
        lines: dict[str, Any] = {}
        for line, entry in zip(self._lines, hasil, strict=True):
            # Any exception (LineUnavailable or otherwise) reads as unreachable —
            # a bug in one line's fetch must not take the other two cards down too.
            if isinstance(entry, BaseException):
                lines[line.line_code] = {"terjangkau": False, "sebab": str(entry)}
            else:
                lines[line.line_code] = {"terjangkau": True, **entry}
        return {"lines": lines}

    async def _satu_line(self, line: LineEndpoint) -> dict[str, Any]:
        return await self._line_client.health_detail(line)

    def antrean(self) -> dict[str, Any]:
        return {
            "pending": self._erp_outbox.pending_count(),
            "gagal": self._erp_outbox.failed_count(),
            "items": self._erp_outbox.daftar_gagal(limit=50),
        }

    def kirim_ulang(self) -> dict[str, Any]:
        return {"dikirim_ulang": self._erp_outbox.requeue_failed()}

    async def plc_baca(self, line_code: str) -> dict[str, Any]:
        """DI snapshot + testable coils for one line. Read-only — safe to open anytime."""
        line = self._require_line(line_code)
        return await self._line_client.plc_state(line)

    async def plc_picu(
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
        if konfirmasi.strip() != _KONFIRMASI_UJI_PLC:
            raise KonfirmasiKurang(f"ketik '{_KONFIRMASI_UJI_PLC}' sebelum memicu coil")
        try:
            hasil = await self._line_client.plc_coil(
                line, coil=coil, requested_by=operator_email
            )
        except LinePlcTolak as exc:
            # Every attempt is logged, hit or refused: a coil that was REFUSED is
            # still an event support needs to see in the trail, same as one fired.
            # logger.warning(), not LogStore.tulis() directly, so this goes through
            # the same SqliteLogHandler as everything else in log_kejadian —
            # that is what applies redaksi() before the row settles on disk.
            logger.warning(
                "UJI PLC: %s memicu coil %s di %s — ditolak line: %s",
                operator_email, coil, line_code, exc,
            )
            if exc.status_code == 409:
                raise PlcSibuk("line sedang memproses truk") from exc
            if exc.status_code == 422:
                raise CoilTidakDikenal(f"coil {coil} tidak dikenal") from exc
            raise
        except LineUnavailable as exc:
            # An unreachable line is the ORDINARY state while a mill is being
            # commissioned or is already broken — exactly when this button gets
            # pressed, and exactly when the trail matters most. LineClient logs
            # its own line (line_client.py) for the network story, but that log
            # line has no idea who the operator is — this one does.
            logger.warning(
                "UJI PLC: %s memicu coil %s di %s — line tidak terjangkau: %s",
                operator_email, coil, line_code, exc,
            )
            raise
        logger.warning(
            "UJI PLC: %s memicu coil %s di %s (fired=%s)",
            operator_email, coil, line_code, hasil.get("fired"),
        )
        return {"line_code": line_code, **hasil}

    def _require_line(self, line_code: str) -> LineEndpoint:
        for line in self._lines:
            if line.line_code == line_code:
                return line
        raise InvalidInput(LINE_TIDAK_DIKENAL, f"line tidak dikenal: {line_code}", line=line_code)

    def versi(self) -> dict[str, Any]:
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
