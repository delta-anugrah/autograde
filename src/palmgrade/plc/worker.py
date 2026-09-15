"""Worker yang bicara ke coupler ODOT CN-8031.

Satu-satunya thread yang menyentuh socket Modbus. Tugasnya empat:
menguras antrean keputusan jadi pulse coil, menahan bit alive PC,
memantulkan discrete input PLC ke memori, dan — sebagai efek samping dari
polling reguler — menahan watchdog ODOT supaya tidak mereset output.
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
        # None = fitur lisensi mati (PC dev / pabrik yang belum dilisensi):
        # perilakunya persis seperti sebelum fitur ini ada.
        self.license_ok = license_ok
        self.inputs: list[bool] = []
        self._queue: queue.Queue[str] = queue.Queue(maxsize=50)
        self._alive_level = False
        self._next_alive_write = 0.0
        # Coil -> level yang gagal ditulis tick sebelumnya. tick() cuma melaporkan
        # perubahan level SEKALI, jadi kalau write-nya gagal, tidak ada yang
        # menagihnya lagi kecuali kita simpan dan coba ulang di tick berikutnya.
        self._failed_writes: dict[int, bool] = {}
        self.dropped_submissions = 0
        # None = belum pernah dievaluasi, jadi evaluasi pertama selalu menulis.
        self._error_level: bool | None = None
        # Kapan level ERROR ditegakkan ulang, terlepas dari ada perubahan atau
        # tidak. Coupler ODOT me-reset output saat link putus (fault action), dan
        # level yang cuma ditulis saat berubah tidak punya siapa pun yang
        # menagihnya naik lagi sesudah tersambung.
        self._next_error_write = 0.0
        # Diset saat shutdown. run_loop mengecek ini SEBELUM tiap tick supaya
        # de-energise di shutdown_plc_worker() tidak balapan dengan tick terakhir.
        self._stop = threading.Event()

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
        if self.client.write_coil(coil, level):
            self._failed_writes.pop(coil, None)
        else:
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

        # 2. Rakit SATU peta {coil: level} untuk seluruh tick ini, lalu tulis
        #    sekali di akhir. Urutan penyusunan penting — entri belakangan
        #    menimpa yang depan, jadi level SEGAR selalu menang atas level basi
        #    pada coil yang sama. Ini yang mematikan runt pulse secara struktural:
        #    dulu retry dan toggle alive menulis terpisah, jadi level basi dan
        #    level segar keluar berurutan dengan jarak ~1ms di coil yang sama.
        writes: dict[int, bool] = dict(self._failed_writes)   # a. retry tick lalu
        self._failed_writes = {}
        writes.update(self.scheduler.tick(now))               # b. pulse segar

        # c. Bit alive — ON statis, itu yang diminta skematik ODOT ("HEARTBIT PC
        #    ON") dan yang dibaca ladder PLC. Ditulis ULANG tiap detik, bukan
        #    sekali saat start: kalau coupler me-reset output waktu koneksi
        #    putus, coil harus naik lagi sendiri begitu nyambung, tanpa restart.
        #    PLC_ALIVE_TOGGLE_MS > 0 menukarnya jadi toggle — lihat config.py.
        #    Langganan habis => coil ini DIMATIKAN. Ladder membacanya sebagai
        #    "PC off" dan seven segment alarm, jadi berhentinya kelihatan di
        #    lantai pabrik. Diam-diam lebih buruk: PLC mengira semuanya normal,
        #    buah lewat tanpa disortir, dan yang dituduh nanti produk kita yang
        #    rusak. Konsekuensi yang diterima: di PLC, "lisensi habis" dan "PC
        #    mati" terlihat sama persis — yang membedakan cuma layar. Coil SPARE
        #    10-15 sudah disepakati dengan pak Ocit untuk TIDAK disentuh, jadi
        #    tidak ada coil terpisah untuk ini.
        if self.settings.plc_coil_alive and now >= self._next_alive_write:
            toggle_ms = self.settings.plc_alive_toggle_ms
            licensed = self.license_ok() if self.license_ok else True
            self._alive_level = (
                False if not licensed else (not self._alive_level) if toggle_ms else True
            )
            for coil in self.settings.plc_coil_alive:
                writes[coil] = self._alive_level
            self._next_alive_write = now + (toggle_ms / 1000.0 if toggle_ms else 1.0)

        # d. Coil ERROR — level, bukan pulse. Ditulis saat berubah, DAN ditegakkan
        #    ulang tiap detik supaya selamat dari reset output milik coupler.
        desired = self._is_unhealthy()
        if desired != self._error_level or now >= self._next_error_write:
            writes[self.settings.plc_coil_error] = desired
            self._error_level = desired
            self._next_error_write = now + 1.0

        # 3. Satu-satunya titik tulis coil dalam satu tick.
        for coil, level in writes.items():
            self._write_coil(coil, level)

        # 4. Baca balik status dari PLC — gagal jangan menimpa state terakhir yang
        #    valid. Sengaja SETELAH write: ini round-trip Modbus yang bisa
        #    menggantung sampai timeout socket (1 detik), dan menaruhnya sebelum
        #    write akan menunda pulse selama itu — pulse telat = buah salah.
        bits = self.client.read_discrete_inputs(0, self.settings.plc_di_count)
        if bits is not None:
            self.inputs = bits
        else:
            logger.warning("Baca discrete input PLC gagal — state input terakhir dipertahankan")

    def _is_unhealthy(self) -> bool:
        # Overflow SENGAJA tidak ikut menentukan ini. Drop adalah steady state yang
        # dideklarasikan di bawah beban (docs/plc-integration.md): kamera bisa ~10
        # keputusan/detik, satu coil muat ~2,5. Kalau drop menaikkan ERROR, coil
        # CAM_N_ERROR menyala sepanjang shift dan artinya berubah jadi "line ini
        # jalan normal". Kedua counter drop tetap dihitung dan tetap di-log — itu
        # diagnostik (dibaca lewat /health/detail), bukan sinyal ke PLC.
        if self.health_check is not None:
            try:
                return not self.health_check()
            except Exception:
                logger.exception("health_check PLC gagal — dianggap tidak sehat")
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
        """Minta run_loop keluar. Aman dipanggil dari thread mana pun, boleh berkali-kali."""
        self._stop.set()

    def deenergise(self) -> None:
        """Matikan semua coil milik line ini. Dipanggil sekali saat shutdown.

        Sengaja tidak lewat `_write_coil`: bookkeeping `_error_level`/`_failed_writes`
        tidak relevan lagi karena tidak akan ada tick berikutnya yang menagih retry.
        Best-effort — gagal dicatat, tidak di-retry, tidak di-raise. SIGTERM di
        tengah pulse (200ms ON dalam siklus ≈410 ms, 2 tick) kalau tidak begini
        meninggalkan coil OK atau NG nyangkut ON sampai watchdog ODOT menyerah.
        """
        coils = [
            self.settings.plc_coil_ok,
            self.settings.plc_coil_ng,
            self.settings.plc_coil_error,
            *(self.settings.plc_coil_alive or ()),
        ]
        for coil in coils:
            try:
                if not self.client.write_coil(coil, False):
                    logger.warning("Gagal mematikan coil %s saat shutdown", coil)
            except Exception:
                logger.exception("Error saat mematikan coil %s saat shutdown", coil)

    def run_loop(self) -> None:
        interval = self.settings.plc_poll_ms / 1000.0
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("PlcWorker.run_once gagal — loop tetap jalan")
            # wait(), bukan sleep(): shutdown tidak perlu menunggu satu poll penuh.
            self._stop.wait(interval)
