"""Worker that talks to the ODOT CN-8031 coupler.

The only thread that touches the Modbus socket. Four jobs: draining the
decision queue into coil pulses, holding the PC alive bit, mirroring the
PLC's discrete inputs into memory, and — as a side effect of regular polling —
holding off the ODOT watchdog so it does not reset the outputs.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class PlcWorker:
    def __init__(
        self,
        client,
        scheduler,
        settings,
        health_check: Callable[[], bool] | None = None,
        license_ok: Callable[[], bool] | None = None,
    ) -> None:
        self.client = client
        self.scheduler = scheduler
        self.settings = settings
        self.health_check = health_check
        # None = licensing feature off (dev PC / an unlicensed mill): behaves
        # exactly as it did before this feature existed.
        self.license_ok = license_ok
        self.inputs: list[bool] = []
        self._queue: queue.Queue[str] = queue.Queue(maxsize=50)
        self._alive_level = False
        self._next_alive_write = 0.0
        # Coil -> level that failed to write on the previous tick. tick() only
        # reports a level CHANGE once, so if the write fails nothing else asks
        # for it again unless we remember it and retry on the next tick.
        self._failed_writes: dict[int, bool] = {}
        self.dropped_submissions = 0
        # None = never evaluated yet, so the first evaluation always writes.
        self._error_level: bool | None = None
        # When the ERROR level is re-asserted, regardless of whether it changed.
        # The ODOT coupler resets its outputs when the link drops (fault
        # action), and a level only written on change has nobody to re-raise
        # it once the link comes back.
        self._next_error_write = 0.0
        # Set on shutdown. run_loop checks this BEFORE every tick so
        # de-energising in shutdown_plc_worker() cannot race the last tick.
        self._stop = threading.Event()
        # Manual piston. `_piston_requested` is written from the HTTP thread and
        # read by run_once; one bool guarded by a small lock is enough, no
        # queue needed — what applies is always the latest request.
        self._piston_lock = threading.Lock()
        self._piston_requested = False
        self._piston_written: bool | None = None     # last level actually written
        self._piston_deadline = 0.0                  # deadline waiting for DI confirmation
        # `scheduler` (PulseScheduler) used to be touched only from run_once's own
        # thread. fire_test_coil() is the first caller from the HTTP thread, so its
        # dict mutations (enqueue/tick both touch `_coils`) now need a lock —
        # same shape as `_piston_lock` above, one small lock per shared field.
        self._scheduler_lock = threading.Lock()

    def submit(self, status: str) -> None:
        """Called from the detection thread. Never blocks, never raises."""
        try:
            self._queue.put_nowait(status)
        except queue.Full:
            self.dropped_submissions += 1
            if self.dropped_submissions == 1 or self.dropped_submissions % 100 == 0:
                logger.warning(
                    "PLC submit queue full — status dropped (total %s).",
                    self.dropped_submissions,
                )

    def request_piston(self, open: bool) -> None:
        """Ask for this line's piston to open (True) or close (False).

        Safe to call from the HTTP thread: all that happens here is storing the
        intent. The coil itself is written by `run_once`, the only thing that
        touches the socket.
        """
        with self._piston_lock:
            self._piston_requested = bool(open)

    def _input_at(self, address: int | None) -> bool | None:
        """One bit of the block we read, addressed the way the panel writes it.

        Every address in compose and in the panel document is ABSOLUTE (M1111),
        while `self.inputs` is just the block that was read, starting at
        `PLC_DI_BASE`. Doing the subtraction here is what lets the MC Protocol
        block start at 200 without any caller learning about it — under Modbus,
        where the base is 0, this is a no-op.

        None = that address is not inside the block we read, which means "not
        known", never "off": reporting a piston closed because nobody told us
        is exactly the lie that gets a hand under it.
        """
        if address is None:
            return None
        offset = address - getattr(self.settings, "plc_di_base", 0)
        if offset < 0 or offset >= len(self.inputs):
            return None
        return bool(self.inputs[offset])

    def piston_state(self) -> dict:
        """Status for the operator screen. `confirmed_open=None` = DI not set."""
        confirmed = self._input_at(getattr(self.settings, "plc_di_manual", None))
        with self._piston_lock:
            return {"requested": self._piston_requested, "confirmed_open": confirmed}

    def fire_test_coil(self, coil: int) -> bool:
        """Queue one test pulse on `coil`, for wiring checks at commissioning.

        Goes through the same scheduler as grading pulses, so it self-clears
        on the next tick — no state left for the caller to clean up. Returns
        False when the pulse queue is full and the request was dropped, NOT
        written: a caller that swallows this would show "fired" for a coil
        that never moved.
        """
        with self._scheduler_lock:
            return self.scheduler.enqueue(coil)

    def _write_coil(self, coil: int, level: bool) -> None:
        if self.client.write_coil(coil, level):
            self._failed_writes.pop(coil, None)
            return
        if level and coil == getattr(self.settings, "plc_coil_manual", None):
            # A failed open request is NOT retried: see block e in run_once.
            with self._piston_lock:
                self._piston_requested = False
            self._piston_written = False
            logger.warning("Piston coil write failed — open request cancelled, not retried")
            return
        self._failed_writes[coil] = level
        logger.warning("PLC coil write failed, will retry next tick: coil=%s level=%s", coil, level)

    def run_once(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now

        # 1. Decision queue -> scheduled pulse
        while True:
            try:
                status = self._queue.get_nowait()
            except queue.Empty:
                break
            coil = self._coil_for(status)
            if coil is None:
                logger.debug("Unknown PLC status, skipped: %r", status)
                continue
            with self._scheduler_lock:
                scheduled = self.scheduler.enqueue(coil)
            if not scheduled:
                if self.scheduler.dropped == 1 or self.scheduler.dropped % 100 == 0:
                    logger.warning(
                        "PLC pulse queue full — signal dropped (total %s). "
                        "Bunches are arriving faster than the PLC can count them.",
                        self.scheduler.dropped,
                    )

        # 2. Build ONE {coil: level} map for this whole tick, then write it once
        #    at the end. The build order matters — a later entry overwrites an
        #    earlier one, so a FRESH level always wins over a stale one on the
        #    same coil. This is what structurally kills the runt pulse: retry
        #    and alive-toggle used to write separately, so a stale level and a
        #    fresh one went out back-to-back ~1ms apart on the same coil.
        writes: dict[int, bool] = dict(self._failed_writes)   # a. last tick's retry
        self._failed_writes = {}
        with self._scheduler_lock:
            writes.update(self.scheduler.tick(now))           # b. fresh pulses

        # c. Alive bit — statically ON, which is what the ODOT schematic asks
        #    for ("HEARTBIT PC ON") and what the PLC ladder reads. Re-written
        #    every second, not just once at start: if the coupler resets its
        #    outputs when the connection drops, the coil must come back up on
        #    its own once reconnected, with no restart needed.
        #    PLC_ALIVE_TOGGLE_MS > 0 turns it into a toggle instead — see
        #    config.py. Subscription expired => this coil is TURNED OFF. The
        #    ladder reads that as "PC off" and raises the seven-segment alarm,
        #    so the stoppage is visible on the mill floor. Silent would be
        #    worse: the PLC would believe everything is normal, bunches would
        #    pass unsorted, and our product would get blamed later. Accepted
        #    consequence: on the PLC side, "licence expired" and "PC down"
        #    look identical — only the screen tells them apart. Coils SPARE
        #    10-15 are agreed with Pak Ocit as untouched, so there is no
        #    separate coil for this.
        if self.settings.plc_coil_alive and now >= self._next_alive_write:
            toggle_ms = self.settings.plc_alive_toggle_ms
            licensed = self.license_ok() if self.license_ok else True
            self._alive_level = (
                False if not licensed else (not self._alive_level) if toggle_ms else True
            )
            for coil in self.settings.plc_coil_alive:
                writes[coil] = self._alive_level
            self._next_alive_write = now + (toggle_ms / 1000.0 if toggle_ms else 1.0)

        # d. ERROR coil — a level, not a pulse. Written on change, AND
        #    re-asserted every second so it survives the coupler's own output
        #    reset.
        #    ⚠️ Dilewati selama ada pulse uji tangan di coil ini (sejak
        #    2026-09-23, saat coil ERROR masuk daftar yang boleh diuji): tanpa
        #    ini pulse naik lalu langsung ditimpa level sehat pada tick yang
        #    sama, coil bergerak beberapa milidetik dan tidak ada yang melihat
        #    di panel. Levelnya kembali berkuasa di tick sesudah pulse selesai
        #    — `_error_level` sengaja TIDAK diperbarui di sini, jadi
        #    perbandingan `desired != self._error_level` yang memulihkannya.
        err_coil = self.settings.plc_coil_error
        desired = self._is_unhealthy()
        sedang_diuji = self._scheduler_is_active(err_coil)
        if not sedang_diuji and (desired != self._error_level or now >= self._next_error_write):
            writes[err_coil] = desired
            self._error_level = desired
            self._next_error_write = now + 1.0

        # e. Manual piston — a level, like ERROR, but NEVER re-asserted: if the
        #    coupler resets its outputs or the link drops, the request is
        #    considered cancelled. Re-asserting it would mean the piston moves
        #    by itself once the connection recovers, with nobody having asked
        #    for it.
        coil_manual = getattr(self.settings, "plc_coil_manual", None)
        if coil_manual is not None:
            with self._piston_lock:
                requested = self._piston_requested
            di_manual = getattr(self.settings, "plc_di_manual", None)
            # `_piston_written is True` guards so this cancellation can only
            # fire AFTER the ON coil has actually been written. Without it,
            # the first tick (deadline still 0.0, `self.inputs` still empty)
            # would immediately cancel a request that was never even sent to
            # the PLC yet.
            if requested and self._piston_written is True and di_manual is not None \
                    and now >= self._piston_deadline:
                # The ladder did not confirm within the deadline: E-stop, motor
                # fault, or manual mode refused. Drop the request so the next
                # click becomes a fresh rising edge (ladder rule #3).
                # `is True` — an address outside the block reads None ("not
                # known"), and that must cancel the request just like an
                # explicit off would, not sail through as truthy.
                if self._input_at(di_manual) is not True:
                    with self._piston_lock:
                        self._piston_requested = requested = False
                    logger.warning("PLC did not confirm piston open — request cancelled")
            if requested != self._piston_written:
                writes[coil_manual] = requested
                self._piston_written = requested
                if requested:
                    self._piston_deadline = now + 2.0

        # 3. The only coil-write point in one tick.
        for coil, level in writes.items():
            self._write_coil(coil, level)

        # 4. Read status back from the PLC — a failure must not overwrite the
        #    last valid state. Deliberately AFTER the write: this is a Modbus
        #    round-trip that can hang until the socket times out (1 second),
        #    and placing it before the write would delay the pulse by that
        #    much — a late pulse means the wrong bunch gets tagged.
        bits = self.client.read_discrete_inputs(
            getattr(self.settings, "plc_di_base", 0), self.settings.plc_di_count
        )
        if bits is not None:
            self.inputs = bits
        else:
            logger.warning("PLC discrete input read failed — keeping the last input state")

    def _scheduler_is_active(self, coil: int) -> bool:
        """Scheduler sedang memegang coil ini (pulse berjalan / tahanan ON).

        `getattr` supaya scheduler pihak ketiga di test lama — yang tidak punya
        `is_active` — tetap jalan seperti sebelumnya, bukan meledak.
        """
        with self._scheduler_lock:
            cek = getattr(self.scheduler, "is_active", None)
            return bool(cek and cek(coil))

    def _is_unhealthy(self) -> bool:
        # Overflow is DELIBERATELY not part of this. Drops are the declared
        # steady state under load (docs/plc-integration.md): the camera can
        # produce ~10 decisions/s, one coil handles ~2.5. If drops raised
        # ERROR, the CAM_N_ERROR coil would stay on for the whole shift and
        # its meaning would flip to "this line is running normally". Both drop
        # counters are still counted and logged — that is diagnostics (read
        # via /health/detail), not a signal to the PLC.
        if self.health_check is not None:
            try:
                return not self.health_check()
            except Exception:
                logger.exception("PLC health_check failed — treated as unhealthy")
                return True
        return False

    def _coil_for(self, status: str) -> int | None:
        normalized = (status or "").strip().lower()
        if normalized == "acc":
            return self.settings.plc_coil_ok
        if normalized == "rej":
            return self.settings.plc_coil_ng
        return None

    def stop(self) -> None:
        """Ask run_loop to exit. Safe to call from any thread, any number of times."""
        self._stop.set()

    def deenergise(self) -> None:
        """Turn off every coil this line owns. Called once at shutdown.

        Deliberately bypasses `_write_coil`: the `_error_level`/`_failed_writes`
        bookkeeping is no longer relevant since there is no next tick left to
        ask for a retry. Best-effort — a failure is logged, not retried, not
        raised. Without this, a SIGTERM mid-pulse (200ms ON in a 400ms cycle,
        2 ticks) would leave the OK or NG coil stuck ON until the ODOT
        watchdog gives up.
        """
        coils = [
            self.settings.plc_coil_ok,
            self.settings.plc_coil_ng,
            self.settings.plc_coil_error,
            *(self.settings.plc_coil_alive or ()),
        ]
        coil_manual = getattr(self.settings, "plc_coil_manual", None)
        if coil_manual is not None:
            coils.append(coil_manual)
        for coil in coils:
            try:
                if not self.client.write_coil(coil, False):
                    logger.warning("Failed to turn off coil %s during shutdown", coil)
            except Exception:
                logger.exception("Error turning off coil %s during shutdown", coil)

    def run_loop(self) -> None:
        interval = self.settings.plc_poll_ms / 1000.0
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("PlcWorker.run_once failed — loop keeps running")
            # wait(), not sleep(): shutdown does not need to wait a full poll interval.
            self._stop.wait(interval)
