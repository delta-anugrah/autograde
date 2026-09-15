"""PLC integration through an ODOT CN-8031 coupler (Modbus-TCP).

Code outside this package normally needs the functions in `__all__` below
(`start_plc_worker`, `shutdown_plc_worker`, `submit_grading`, `inputs`,
`diagnostics`, `request_piston`, `piston_state`, `picu_coil`, `testable_coils`).
With PLC_ENABLED=false they are all no-ops and no thread runs. `ModbusPlcClient`,
`PlcWorker` and `PulseScheduler` are exported too, for callers that assemble a
worker themselves (tests, mainly). Full coil map: docs/plc-integration.md.
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
    "picu_coil",
    "piston_state",
    "request_piston",
    "shutdown_plc_worker",
    "start_plc_worker",
    "submit_grading",
    "testable_coils",
]

logger = logging.getLogger(__name__)

# One process = one line = one PLC connection, so a single instance is correct.
_worker: PlcWorker | None = None


def start_plc_worker(
    settings,
    health_check: Callable[[], bool] | None = None,
    license_ok: Callable[[], bool] | None = None,
) -> PlcWorker | None:
    """Build the worker from Settings. Returns None when the PLC is disabled.

    Running run_loop() on its own thread is the caller's job.
    """
    global _worker
    if _worker is not None:
        # None, NOT the existing worker: callers use `is not None` to decide
        # whether to start a thread. Handing back the same worker would save a
        # coupler slot but run a SECOND thread through the same run_loop over the
        # same ModbusTcpClient socket — interleaved writes and mismatched
        # transaction ids. Far worse than refusing.
        logger.warning(
            "start_plc_worker called again while a PLC worker is running — "
            "ignoring this call (no second client, no second thread)"
        )
        return None
    if not settings.plc_enabled:
        return None
    if not settings.plc_host:
        logger.warning("PLC_ENABLED=true but PLC_HOST is empty — PLC not started")
        return None
    if settings.plc_pulse_ms < settings.plc_poll_ms:
        # run_loop only wakes every PLC_POLL_MS, so that is the real time
        # resolution. A pulse shorter than one tick cannot be produced: its ON
        # and OFF land on the same tick and the PLC never sees a rising edge.
        # Warn only — no raise, no clamping: correct tuning depends on the PLC
        # on site, and silently guessing a replacement value is more dangerous
        # than passing the value through and saying so loudly.
        logger.warning(
            "PLC_PULSE_MS (%s) is below PLC_POLL_MS (%s) — the real resolution is "
            "PLC_POLL_MS, so a pulse this short may never be seen by the PLC. "
            "Raise PLC_PULSE_MS or lower PLC_POLL_MS.",
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
        license_ok=license_ok,
    )
    logger.info(
        "PLC on: %s:%s, coil OK/NG/ERROR = %s/%s/%s, alive = %s",
        settings.plc_host,
        settings.plc_port,
        settings.plc_coil_ok,
        settings.plc_coil_ng,
        settings.plc_coil_error,
        settings.plc_coil_alive or "(off)",
    )
    return _worker


def submit_grading(status: str) -> None:
    """Send one grading verdict ('acc' / 'rej') to the PLC. No-op when off."""
    if _worker is not None:
        _worker.submit(status)


def inputs() -> list[bool]:
    """Latest discrete-input snapshot from the PLC (motor fault + E-stop)."""
    return _worker.inputs if _worker is not None else []


def request_piston(open: bool) -> bool:
    """Minta piston line ini buka/tutup. False = PLC mati atau coil belum diset.

    False bukan error: selama panel belum mengalokasikan coil, tombolnya memang
    harus mati di layar, bukan berpura-pura bekerja.
    """
    worker = _worker
    if worker is None or getattr(worker.settings, "plc_coil_manual", None) is None:
        return False
    worker.request_piston(open)
    return True


def piston_state() -> dict | None:
    """Status piston untuk konsol. None kalau PLC mati atau coil belum diset."""
    worker = _worker
    if worker is None or getattr(worker.settings, "plc_coil_manual", None) is None:
        return None
    return worker.piston_state()


def testable_coils(settings) -> frozenset[int]:
    """Coils safe to pulse by hand from the commissioning test screen.

    OK/NG/manual-piston only, and only the ones actually configured (may be
    None). `plc_coil_alive` (coil 9, "HEARTBIT PC ON") is deliberately NOT
    here: firing it by hand can make the panel believe the PC died and raise
    a seven-segment alarm. `plc_coil_error` is excluded too — it is a level
    driven by health_check(), not something a hand pulse should perturb.
    """
    coils = {settings.plc_coil_ok, settings.plc_coil_ng}
    manual = getattr(settings, "plc_coil_manual", None)
    if manual is not None:
        coils.add(manual)
    return frozenset(coils)


def picu_coil(coil: int) -> bool:
    """Fire one test coil for commissioning. False = PLC off or pulse dropped.

    Both cases mean "nothing moved" and must read the same way on the test
    screen — a caller that treats them differently risks reporting a fired
    coil that never actually pulsed.
    """
    worker = _worker
    if worker is None:
        return False
    return worker.picu_coil(coil)


def diagnostics() -> dict | None:
    """PLC snapshot for /health/detail. None when the PLC is off or not started.

    This is the only way to read the E-stop (`inputs[11]` since the panel grew to
    11 motors on 2026-09-15; it was `inputs[10]`) and watch both drop
    counters from outside the container. Both are diagnostics only — nothing
    decides anything from them — so `None` while the PLC is off is the right
    answer, not an error.

    `inputs` is copied: a caller must not be able to mutate worker state.
    """
    worker = _worker
    if worker is None:
        return None
    return {
        "inputs": list(worker.inputs),
        "dropped_pulses": worker.scheduler.dropped,
        "dropped_submissions": worker.dropped_submissions,
        "piston": piston_state(),
    }


def shutdown_plc_worker(thread: threading.Thread | None = None, timeout: float = 2.0) -> None:
    """Stop the worker, drop every coil, close the socket. Safe when PLC is off.

    The order is mandatory: stop the loop FIRST, wait for the thread to actually
    exit, and only then write OFF. Reversed, the last tick races us and switches
    back on the coils we just cleared. `thread` may be None (PLC disabled, or the
    caller does not hold the thread) — without a join, `_stop` is still set.

    All best-effort: this runs on the shutdown path, so it never raises and the
    singleton is always cleared even if the link died first.
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
                    "PLC thread still alive after %ss — dropping coils best-effort anyway", timeout
                )
        worker.deenergise()
        worker.client.close()
    except Exception:
        logger.exception("PLC shutdown was not clean — continuing anyway")
    finally:
        _worker = None
