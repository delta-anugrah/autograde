"""Reads the live weighbridge weight from the PLC (console only, 2026-10-06).

One MC Protocol connection of the console's own, separate from the three lines'
(one user per port on the Q03UDECPU, so the scale needs its own Open Setting port,
1028 by default). The words become kilograms in `domain/timbangan_live.py`; this
class only asks the PLC and says None when it does not answer.

Blocking (pymcprotocol is a plain socket): the worker calls `baca()` in a thread.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ..core.config import Settings
from ..domain.timbangan_live import Bacaan, alamat_bit, alamat_word, gabung_kata, ke_kg
from .mc_client import McProtocolPlcClient

logger = logging.getLogger(__name__)


class _KlienKata(Protocol):
    def read_words(self, headdevice: str, count: int) -> list[int] | None: ...
    def read_bits(self, headdevice: str, count: int) -> list[bool] | None: ...
    def close(self) -> None: ...


class PembacaTimbangan:
    def __init__(
        self,
        client: _KlienKata,
        *,
        register: str,
        kata: int = 2,
        desimal: int = 0,
        bit_stabil: str | None = None,
        bit_error: str | None = None,
    ) -> None:
        self._client = client
        self._register = register
        self._kata = kata
        self._desimal = desimal
        self._bit_stabil = bit_stabil
        self._bit_error = bit_error

    def baca(self) -> Bacaan | None:
        """One reading, or None when any configured part of it did not answer.

        A failed read of a configured bit fails the whole reading: half a reading
        would show a weight as stable that nobody confirmed.
        """
        kata = self._client.read_words(self._register, self._kata)
        if kata is None or len(kata) != self._kata:
            return None
        stabil: bool | None = None
        if self._bit_stabil is not None:
            bits = self._client.read_bits(self._bit_stabil, 1)
            if not bits:
                return None
            stabil = bits[0]
        error = False
        if self._bit_error is not None:
            bits = self._client.read_bits(self._bit_error, 1)
            if not bits:
                return None
            error = bits[0]
        return Bacaan(kg=ke_kg(gabung_kata(kata), self._desimal), stabil=stabil, error=error)

    def close(self) -> None:
        self._client.close()


def build_pembaca_timbangan(settings: Settings) -> PembacaTimbangan | None:
    """The reader, or None while the scale is not configured.

    A broken value turns the feature off with one warning instead of stopping the
    console (same reason as `_plc_int`: a typo at commissioning must not take the
    operator screen down).
    """
    mentah = settings.scale_plc_register.strip()
    if not mentah:
        return None
    register = alamat_word(mentah)
    if register is None:
        logger.warning("SCALE_PLC_REGISTER=%r is not a word device (e.g. D100); live scale is off", mentah)
        return None
    if not settings.scale_plc_host:
        logger.warning("SCALE_PLC_REGISTER is set but SCALE_PLC_HOST and PLC_HOST are empty; live scale is off")
        return None
    kata = settings.scale_plc_words
    if kata not in (1, 2):
        logger.warning("SCALE_PLC_WORDS=%s must be 1 or 2; using 2 (32-bit)", kata)
        kata = 2
    desimal = settings.scale_plc_decimals
    if not 0 <= desimal <= 3:
        logger.warning("SCALE_PLC_DECIMALS=%s must be 0 to 3; using 0", desimal)
        desimal = 0
    bits: dict[str, str | None] = {}
    for nama, nilai in (
        ("SCALE_PLC_STABLE_BIT", settings.scale_plc_stable_bit),
        ("SCALE_PLC_ERROR_BIT", settings.scale_plc_error_bit),
    ):
        bits[nama] = alamat_bit(nilai)
        if nilai.strip() and bits[nama] is None:
            logger.warning("%s=%r is not a bit device (e.g. M2000); that signal is not used", nama, nilai)
    client = McProtocolPlcClient(host=settings.scale_plc_host, port=settings.scale_plc_port)
    return PembacaTimbangan(
        client,
        register=register,
        kata=kata,
        desimal=desimal,
        bit_stabil=bits["SCALE_PLC_STABLE_BIT"],
        bit_error=bits["SCALE_PLC_ERROR_BIT"],
    )
