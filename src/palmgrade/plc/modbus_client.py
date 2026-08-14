"""Klien Modbus-TCP untuk coupler ODOT CN-8031.

Satu-satunya tempat di repo ini yang menyentuh API pymodbus. Semua method
mengembalikan nilai sentinel (False / None) alih-alih melempar exception:
PlcWorker berjalan di thread panjang dan tidak boleh mati karena kabel dicabut.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

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
            logger.warning("PLC connect ke %s:%s gagal: %s", self._host, self._port, exc)
            self.connected = False
        return self.connected

    def _drop(self, exc: Exception) -> None:
        logger.warning("PLC I/O gagal (%s) — menandai terputus, akan reconnect", exc)
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
        if reply.isError():
            logger.warning("PLC menolak write coil %s = %s", address, value)
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
