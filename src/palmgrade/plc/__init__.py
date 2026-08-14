"""Integrasi PLC lewat coupler ODOT CN-8031 (Modbus-TCP).

Kode di luar paket ini hanya boleh menyentuh tiga fungsi di bawah. Kalau
PLC_ENABLED=false, ketiganya jadi no-op dan tidak ada thread yang jalan.
Coil map lengkap: docs/plc-integration.md.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .modbus_client import ModbusPlcClient
from .pulse import PulseScheduler
from .worker import PlcWorker

__all__ = [
    "ModbusPlcClient",
    "PlcWorker",
    "PulseScheduler",
    "inputs",
    "start_plc_worker",
    "submit_grading",
]

logger = logging.getLogger(__name__)

# Satu proses = satu line = satu koneksi PLC, jadi satu instance sudah benar.
_worker: PlcWorker | None = None


def start_plc_worker(settings, health_check: Callable[[], bool] | None = None) -> PlcWorker | None:
    """Bangun worker dari Settings. Kembalikan None kalau fitur PLC dimatikan.

    Pemanggil bertanggung jawab menjalankan run_loop() di thread-nya sendiri.
    """
    global _worker
    if not settings.plc_enabled:
        return None
    if not settings.plc_host:
        logger.warning("PLC_ENABLED=true tapi PLC_HOST kosong — PLC tidak dijalankan")
        return None

    _worker = PlcWorker(
        client=ModbusPlcClient(
            host=settings.plc_host,
            port=settings.plc_port,
            unit_id=settings.plc_unit_id,
        ),
        scheduler=PulseScheduler(
            pulse_s=settings.plc_pulse_ms / 1000.0,
            gap_s=settings.plc_pulse_gap_ms / 1000.0,
            queue_max=settings.plc_queue_max,
        ),
        settings=settings,
        health_check=health_check,
    )
    logger.info(
        "PLC aktif: %s:%s, coil OK/NG/ERROR = %s/%s/%s, alive = %s",
        settings.plc_host,
        settings.plc_port,
        settings.plc_coil_ok,
        settings.plc_coil_ng,
        settings.plc_coil_error,
        settings.plc_coil_alive or "(mati)",
    )
    return _worker


def submit_grading(status: str) -> None:
    """Kirim satu keputusan grading ('acc' / 'rej') ke PLC. No-op kalau PLC mati."""
    if _worker is not None:
        _worker.submit(status)


def inputs() -> list[bool]:
    """Snapshot discrete input terakhir dari PLC (motor fault + E-stop)."""
    return _worker.inputs if _worker is not None else []
