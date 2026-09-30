"""Klien Modbus-TCP untuk coupler ODOT CN-8031.

Satu-satunya tempat di repo ini yang menyentuh API pymodbus. Semua method
mengembalikan nilai sentinel (False / None) alih-alih melempar exception:
PlcWorker berjalan di thread panjang dan tidak boleh mati karena kabel dicabut.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .jejak_sambungan import JejakSambunganPlc

logger = logging.getLogger(__name__)


class ModbusPlcClient:
    def __init__(
        self,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        _client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._factory = _client_factory or self._default_factory
        self._client: Any = None
        self.connected = False
        self._jejak = JejakSambunganPlc(host, port)

    def _default_factory(self) -> Any:
        from pymodbus.client import ModbusTcpClient

        return ModbusTcpClient(self._host, port=self._port, timeout=1.0)

    def _ensure(self) -> bool:
        if self.connected and self._client is not None:
            return True
        try:
            self._client = self._factory()
            self.connected = bool(self._client.connect())
        except Exception as exc:
            self._jejak.gagal_sambung(exc)
            self.connected = False
            # `return self.connected` di bawah sudah False di sini juga, tapi
            # `except` berhenti di sini SENGAJA: baris `if not self.connected`
            # sesudahnya cuma untuk kasus pymodbus MENJAWAB False (bukan
            # melempar), jadi tidak boleh ikut jalan dan menulis WARNING kedua
            # untuk exception yang sama.
            return False
        if not self.connected:
            # pymodbus menjawab False, bukan melempar, untuk host yang tidak menjawab.
            self._jejak.gagal_sambung("koneksi Modbus ditolak atau tidak dijawab")
        return self.connected

    def _drop(self, exc: Exception) -> None:
        self._jejak.terputus(exc)
        self.connected = False
        try:
            if self._client is not None:
                self._client.close()
        except Exception as close_exc:
            logger.debug("Socket close gagal di _drop: %s", close_exc)
        self._client = None

    def write_coil(self, address: int, value: bool) -> bool:
        if not self._ensure():
            return False
        try:
            reply = self._client.write_coil(address, value, slave=self._unit_id)
        except Exception as exc:
            self._drop(exc)
            return False
        # Ada jawaban: sambungannya hidup, walau isinya penolakan. Penolakan yang
        # berulang dicatat PlcWorker sekali per kejadian, jadi di sini cuma DEBUG.
        self._jejak.berhasil()
        if reply.isError():
            logger.debug("PLC menolak write coil %s = %s", address, value)
            return False
        return True

    def read_discrete_inputs(self, start: int, count: int) -> list[bool] | None:
        if not self._ensure():
            return None
        try:
            reply = self._client.read_discrete_inputs(start, count, slave=self._unit_id)
        except Exception as exc:
            self._drop(exc)
            return None
        self._jejak.berhasil()
        if reply.isError():
            return None
        return list(reply.bits)[:count]

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:
                logger.debug("Socket close gagal: %s", exc)
        self._client = None
        self.connected = False
