"""Worker yang bicara ke coupler ODOT CN-8031.

Satu-satunya thread yang menyentuh socket Modbus. Tugasnya empat:
menguras antrean keputusan jadi pulse coil, meng-toggle bit alive line ini,
memantulkan discrete input PLC ke memori, dan — sebagai efek samping dari
polling reguler — menahan watchdog ODOT supaya tidak mereset output.
"""

from __future__ import annotations

import logging
import queue
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
    ) -> None:
        self.client = client
        self.scheduler = scheduler
        self.settings = settings
        self.health_check = health_check
        self.inputs: list[bool] = []
        self._queue: queue.Queue[str] = queue.Queue(maxsize=50)
        self._alive_level = False
        self._next_alive_toggle = 0.0
        # Coil -> level yang gagal ditulis tick sebelumnya. tick() cuma melaporkan
        # perubahan level SEKALI, jadi kalau write-nya gagal, tidak ada yang
        # menagihnya lagi kecuali kita simpan dan coba ulang di tick berikutnya.
        self._failed_writes: dict[int, bool] = {}
        self.dropped_submissions = 0

    def submit(self, status: str) -> None:
        """Dipanggil dari thread deteksi. Tidak pernah blocking, tidak pernah raise."""
        try:
            self._queue.put_nowait(status)
        except queue.Full:
            self.dropped_submissions += 1
            if self.dropped_submissions == 1 or self.dropped_submissions % 100 == 0:
                logger.warning(
                    "Antrean submit PLC penuh — status dibuang (total %s).",
                    self.dropped_submissions,
                )

    def _write_coil(self, coil: int, level: bool) -> None:
        if not self.client.write_coil(coil, level):
            self._failed_writes[coil] = level
            logger.warning("Write coil PLC gagal, akan dicoba lagi tick berikutnya: coil=%s level=%s", coil, level)

    def run_once(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now

        # 1. Antrean keputusan -> pulse terjadwal
        while True:
            try:
                status = self._queue.get_nowait()
            except queue.Empty:
                break
            coil = self._coil_for(status)
            if coil is None:
                logger.debug("Status PLC tidak dikenal, dilewati: %r", status)
                continue
            if not self.scheduler.enqueue(coil):
                if self.scheduler.dropped == 1 or self.scheduler.dropped % 100 == 0:
                    logger.warning(
                        "Antrean pulse PLC penuh — sinyal dibuang (total %s). "
                        "Buah datang lebih cepat dari yang bisa dihitung PLC.",
                        self.scheduler.dropped,
                    )

        # 2. Terapkan perubahan level coil — gagal tick lalu ikut dicoba ulang,
        # ditimpa oleh perubahan segar kalau coil yang sama berubah lagi.
        pending = {**self._failed_writes, **self.scheduler.tick(now)}
        self._failed_writes = {}
        for coil, level in pending.items():
            self._write_coil(coil, level)

        # 3. Bit alive — toggle, bukan ON statis, supaya proses yang hang ikut ketahuan
        if self.settings.plc_coil_alive and now >= self._next_alive_toggle:
            self._alive_level = not self._alive_level
            for coil in self.settings.plc_coil_alive:
                self._write_coil(coil, self._alive_level)
            self._next_alive_toggle = now + 1.0

        # 4. Baca balik status dari PLC — gagal jangan menimpa state terakhir yang valid
        bits = self.client.read_discrete_inputs(0, self.settings.plc_di_count)
        if bits is not None:
            self.inputs = bits
        else:
            logger.warning("Baca discrete input PLC gagal — state input terakhir dipertahankan")

    def _coil_for(self, status: str) -> int | None:
        normalized = (status or "").strip().lower()
        if normalized == "acc":
            return self.settings.plc_coil_ok
        if normalized == "rej":
            return self.settings.plc_coil_ng
        return None

    def run_loop(self) -> None:
        interval = self.settings.plc_poll_ms / 1000.0
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("PlcWorker.run_once gagal — loop tetap jalan")
            time.sleep(interval)
