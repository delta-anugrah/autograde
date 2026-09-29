"""Tab Status → Antrean line (support, batch 2.4): antrean janjang tiap line ke konsol.

Alur saja: HTTP ke line ada di `LineClient` (kunci `INTERNAL_SECRET`, penolakan =
`LINE_MENOLAK`), antreannya sendiri milik line (`/internal/outbox*`). Line yang
mati atau menolak kunci tetap dapat barisnya sendiri beserta sebabnya: justru itu
yang paling perlu dilihat, dan satu line tidak boleh mengosongkan layar dua lainnya.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from ..core.config import LineEndpoint
from ..domain.operator_error import (
    LINE_TIDAK_DIKENAL,
    LINE_TIDAK_MENJAWAB,
    InvalidInput,
    OperatorError,
)
from ..integrations.notifications.line_client import LineUnavailable

logger = logging.getLogger(__name__)

#: Tenggat satu line di `ringkasan()`, di bawah timeout `LineClient` (5 dtk baca):
#: satu line yang macet tidak boleh menahan layar yang disegarkan tiap 5 detik.
BATAS_TUNGGU_LINE_S = 3.0


class KlienAntreanLine(Protocol):
    async def antrean_line(self, line: LineEndpoint) -> dict[str, Any]: ...

    async def kirim_ulang_antrean_line(self, line: LineEndpoint) -> int: ...


class PantauAntreanLine:
    def __init__(
        self,
        line_client: KlienAntreanLine,
        lines: tuple[LineEndpoint, ...],
        *,
        batas_tunggu_s: float = BATAS_TUNGGU_LINE_S,
    ) -> None:
        self._client = line_client
        self._lines = tuple(lines)
        self._batas_tunggu_s = batas_tunggu_s

    async def ringkasan(self) -> dict[str, Any]:
        hasil = await asyncio.gather(
            *(self._antrean(line) for line in self._lines), return_exceptions=True
        )
        return {
            "lines": {
                line.line_code: _baris(line, isi) for line, isi in zip(self._lines, hasil, strict=True)
            }
        }

    async def _antrean(self, line: LineEndpoint) -> Any:
        try:
            return await asyncio.wait_for(self._client.antrean_line(line), self._batas_tunggu_s)
        except TimeoutError as exc:
            raise LineUnavailable(
                LINE_TIDAK_MENJAWAB,
                f"{line.line_code} did not answer within {self._batas_tunggu_s:g} s",
                line=line.name,
            ) from exc

    async def kirim_ulang(self, line_code: str, *, oleh: str) -> dict[str, Any]:
        """Suruh satu line mengirim seluruh antreannya sekarang; tiap tekanan dicatat
        WARNING menyebut pelakunya (tab Log), berhasil atau gagal."""
        line = self._line(line_code)
        try:
            dijadwalkan = await self._client.kirim_ulang_antrean_line(line)
        except OperatorError as exc:
            logger.warning("Kirim Ulang antrean %s oleh %s gagal: %s", line_code, oleh, exc)
            raise
        logger.warning(
            "Kirim Ulang antrean %s oleh %s: %d janjang dijadwalkan kirim sekarang",
            line_code, oleh, dijadwalkan,
        )
        return {"line_code": line_code, "dijadwalkan": dijadwalkan}

    def _line(self, line_code: str) -> LineEndpoint:
        for line in self._lines:
            if line.line_code == line_code:
                return line
        raise InvalidInput(LINE_TIDAK_DIKENAL, f"unknown line: {line_code}", line=line_code)


def _baris(line: LineEndpoint, isi: Any) -> dict[str, Any]:
    """Satu baris layar dari jawaban satu line, atau dari alasan line itu tidak menjawab."""
    if isinstance(isi, OperatorError):
        return {"terjangkau": False, "kode": isi.code, "status": isi.params.get("status"), "pesan": str(isi)}
    if isinstance(isi, Exception):
        return {"terjangkau": False, "kode": LINE_TIDAK_MENJAWAB, "status": None, "pesan": str(isi)}
    if isinstance(isi, BaseException):
        raise isi
    if not isinstance(isi, dict):
        # Jawaban cacat satu line jadi baris galat line itu saja, bukan 500 seluruh layar.
        pesan = f"{line.line_code} answered {type(isi).__name__}, not an object"
        return {"terjangkau": False, "kode": LINE_TIDAK_MENJAWAB, "status": None, "pesan": pesan}
    return {"terjangkau": True, **isi}
