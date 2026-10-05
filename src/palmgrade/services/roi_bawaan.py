"""The detection box this PC uses when the console never set one (2026-10-05).

Settings shows four empty inputs for "each line keeps its own box", and support could not see
which box that was. `ROI_*` lives in the lines' environment, not the console's, so the console
asks the lines: all three read the same `.env`, so the first line that answers, in line order,
speaks for the PC. All three are asked side by side: a dead line costs its timeout once, not
once per line.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any, Protocol

from ..core.config import LineEndpoint
from ..domain.setelan_grading import BATAS_KOTAK, KOTAK

logger = logging.getLogger(__name__)


class PembacaSetelanLine(Protocol):
    async def setelan_aktif(self, line: LineEndpoint) -> dict[str, Any]: ...


def _kotak_sah(nilai: Any) -> tuple[int, int, int, int] | None:
    """Four whole numbers within the screen's own limits, or None for anything else."""
    if not isinstance(nilai, list | tuple) or len(nilai) != len(KOTAK):
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= BATAS_KOTAK for v in nilai):
        return None
    return tuple(nilai)  # type: ignore[return-value]


async def roi_bawaan(lines: Sequence[LineEndpoint], klien: PembacaSetelanLine) -> dict[str, Any]:
    """`roi_x1..roi_y2` of the PC's own box and the line that told, or all None when no line
    answers with one (dead, or an image from before 2026-10-05)."""
    jawaban = await asyncio.gather(*(klien.setelan_aktif(line) for line in lines), return_exceptions=True)
    for line, jawab in zip(lines, jawaban, strict=True):
        if isinstance(jawab, BaseException):
            logger.debug("%s: kotak bawaan tidak terbaca (%s)", line.line_code, jawab)
            continue
        kotak = _kotak_sah((jawab or {}).get("roi_env"))
        if kotak is not None:
            return {**dict(zip(KOTAK, kotak, strict=True)), "line_code": line.line_code}
    return {**dict.fromkeys(KOTAK), "line_code": None}
