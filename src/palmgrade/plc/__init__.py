"""Integrasi PLC lewat coupler ODOT CN-8031 (Modbus-TCP).

Kode di luar paket ini biasanya hanya butuh lima fungsi: `start_plc_worker`,
`shutdown_plc_worker`, `submit_grading`, `inputs`, `diagnostics`. Kalau
PLC_ENABLED=false, kelimanya jadi no-op dan tidak ada thread yang jalan.
`ModbusPlcClient`, `PlcWorker`, `PulseScheduler`
turut diekspor untuk pemanggil yang perlu merakit worker sendiri (mis. test).
Coil map lengkap: docs/plc-integration.md.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from .modbus_client import ModbusPlcClient
from .pulse import PulseScheduler
from .worker import PlcWorker

__all__ = [
    "ModbusPlcClient",
    "PlcWorker",
    "PulseScheduler",
    "diagnostics",
    "inputs",
    "shutdown_plc_worker",
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
    if _worker is not None:
        # None, BUKAN worker yang sudah ada: pemanggil memakai `is not None` untuk
        # memutuskan apakah perlu start thread. Mengembalikan worker yang sama
        # menghemat satu slot coupler tapi menjalankan thread KEDUA di run_loop
        # yang sama, di atas socket ModbusTcpClient yang sama — ADU interleaved
        # dan transaction id tidak cocok. Itu jauh lebih buruk.
        logger.warning(
            "start_plc_worker dipanggil lagi padahal worker PLC sudah jalan — "
            "panggilan ini diabaikan (tidak ada client dan thread kedua)"
        )
        return None
    if not settings.plc_enabled:
        return None
    if not settings.plc_host:
        logger.warning("PLC_ENABLED=true tapi PLC_HOST kosong — PLC tidak dijalankan")
        return None
    if settings.plc_pulse_ms < settings.plc_poll_ms:
        # run_loop cuma bangun tiap PLC_POLL_MS, jadi itulah resolusi waktu yang
        # sebenarnya. Pulse yang lebih pendek dari satu tick tidak bisa
        # dihasilkan: ON dan OFF-nya jatuh di tick yang sama dan PLC tidak pernah
        # melihat rising edge-nya. Warning saja — tidak raise dan tidak di-clamp,
        # karena tuning yang benar tergantung PLC di lapangan, dan menebak-nebak
        # nilai pengganti diam-diam lebih berbahaya daripada meneruskan apa
        # adanya sambil bilang keras-keras.
        logger.warning(
            "PLC_PULSE_MS (%s) lebih kecil dari PLC_POLL_MS (%s) — resolusi waktu "
            "sebenarnya adalah PLC_POLL_MS, jadi pulse selebar ini bisa tidak "
            "pernah terlihat PLC. Naikkan PLC_PULSE_MS atau turunkan PLC_POLL_MS.",
            settings.plc_pulse_ms,
            settings.plc_poll_ms,
        )

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


def diagnostics() -> dict | None:
    """Snapshot PLC untuk /health/detail. None kalau PLC mati atau belum jalan.

    Ini satu-satunya cara membaca E-stop (`inputs[10]`) dan memantau kedua
    counter drop dari luar kontainer. Keduanya cuma diagnostik — tidak ada yang
    memakainya untuk mengambil keputusan, jadi `None` saat PLC mati adalah
    jawaban yang benar, bukan error.

    `inputs` disalin: pemanggil tidak boleh bisa mengubah state worker.
    """
    worker = _worker
    if worker is None:
        return None
    return {
        "inputs": list(worker.inputs),
        "dropped_pulses": worker.scheduler.dropped,
        "dropped_submissions": worker.dropped_submissions,
    }


def shutdown_plc_worker(thread: threading.Thread | None = None, timeout: float = 2.0) -> None:
    """Hentikan worker, matikan semua coil, tutup socket. Aman kalau PLC mati.

    Urutan wajib: hentikan loop DULU, tunggu thread-nya benar-benar keluar, baru
    tulis OFF. Kalau dibalik, tick terakhir balapan dengan kita dan menyalakan
    ulang coil yang baru saja dimatikan. `thread` boleh None (mis. PLC dimatikan,
    atau pemanggil tidak memegang thread-nya) — tanpa join, `_stop` tetap diset.

    Seluruhnya best-effort: dipanggil di jalur shutdown, jadi tidak pernah raise
    dan singleton selalu dibersihkan walau link sudah mati duluan.
    """
    global _worker
    worker = _worker
    if worker is None:
        return
    try:
        worker.stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning(
                    "Thread PLC belum keluar setelah %ss — coil tetap dimatikan best-effort", timeout
                )
        worker.deenergise()
        worker.client.close()
    except Exception:
        logger.exception("Shutdown PLC tidak bersih — dilanjutkan")
    finally:
        _worker = None
