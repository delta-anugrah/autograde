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

logger = logging.getLogger(__name__)


class KlienAntreanLine(Protocol):
    async def antrean_line(self, line: LineEndpoint) -> dict[str, Any]: ...

    async def kirim_ulang_antrean_line(self, line: LineEndpoint) -> int: ...


class PantauAntreanLine:
    def __init__(self, line_client: KlienAntreanLine, lines: tuple[LineEndpoint, ...]) -> None:
        self._client = line_client
        self._lines = tuple(lines)

    async def ringkasan(self) -> dict[str, Any]:
        hasil = await asyncio.gather(
            *(self._client.antrean_line(line) for line in self._lines), return_exceptions=True
        )
        return {
            "lines": {line.line_code: _baris(isi) for line, isi in zip(self._lines, hasil, strict=True)}
        }

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


def _baris(isi: Any) -> dict[str, Any]:
    """Satu baris layar dari jawaban satu line, atau dari alasan line itu tidak menjawab."""
    if isinstance(isi, OperatorError):
        return {"terjangkau": False, "kode": isi.code, "status": isi.params.get("status"), "pesan": str(isi)}
    if isinstance(isi, Exception):
        return {"terjangkau": False, "kode": LINE_TIDAK_MENJAWAB, "status": None, "pesan": str(isi)}
    if isinstance(isi, BaseException):
        raise isi
    return {"terjangkau": True, **isi}
