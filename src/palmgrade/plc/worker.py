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
        # Piston manual. `_piston_requested` ditulis dari thread HTTP dan dibaca
        # run_once; satu bool dilindungi lock kecil sudah cukup, tidak perlu
        # antrean — yang berlaku selalu permintaan terakhir.
        self._piston_lock = threading.Lock()
        self._piston_requested = False
        self._piston_written: bool | None = None     # level terakhir yang benar-benar ditulis
        self._piston_deadline = 0.0                  # batas tunggu konfirmasi DI
        # `scheduler` (PulseScheduler) used to be touched only from run_once's own
        # thread. picu_coil() is the first caller from the HTTP thread, so its
        # dict mutations (enqueue/tick both touch `_coils`) now need a lock —
        # same shape as `_piston_lock` above, one small lock per shared field.
        self._scheduler_lock = threading.Lock()

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

    def request_piston(self, open: bool) -> None:
        """Minta piston line ini buka (True) atau tutup (False).

        Aman dipanggil dari thread HTTP: yang terjadi di sini cuma menyimpan
        niat. Coil-nya ditulis `run_once`, satu-satunya penyentuh socket.
        """
        with self._piston_lock:
            self._piston_requested = bool(open)

    def piston_state(self) -> dict:
        """Status untuk layar operator. `confirmed_open=None` = DI belum diset."""
        coil = getattr(self.settings, "plc_di_manual", None)
        confirmed = None
        if coil is not None and coil < len(self.inputs):
            confirmed = bool(self.inputs[coil])
        with self._piston_lock:
            return {"requested": self._piston_requested, "confirmed_open": confirmed}

    def picu_coil(self, coil: int) -> bool:
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
            # Permintaan buka yang gagal TIDAK di-retry: lihat blok e di run_once.
            with self._piston_lock:
                self._piston_requested = False
            self._piston_written = False
            logger.warning("Tulis coil piston gagal — permintaan buka dibatalkan, bukan diulang")
            return
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
            with self._scheduler_lock:
                terjadwal = self.scheduler.enqueue(coil)
            if not terjadwal:
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
        with self._scheduler_lock:
            writes.update(self.scheduler.tick(now))           # b. pulse segar

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

        # e. Piston manual — level, seperti ERROR, tapi TIDAK pernah ditegakkan
        #    ulang: kalau coupler me-reset output atau link putus, permintaan
        #    dianggap batal. Menegakkannya kembali berarti piston bergerak
        #    sendiri saat koneksi pulih, tanpa ada orang yang memintanya.
        coil_manual = getattr(self.settings, "plc_coil_manual", None)
        if coil_manual is not None:
            with self._piston_lock:
                minta = self._piston_requested
            di_manual = getattr(self.settings, "plc_di_manual", None)
            # `_piston_written is True` menjaga supaya pembatalan ini baru bisa
            # menyala SESUDAH coil ON benar-benar ditulis. Tanpa itu, tick
            # pertama (deadline masih 0.0, `self.inputs` masih kosong) langsung
            # membatalkan permintaan yang belum sempat dikirim ke PLC.
            if minta and self._piston_written is True and di_manual is not None \
                    and now >= self._piston_deadline:
                # Ladder tidak membenarkan dalam tenggang: E-stop, motor fault,
                # atau mode manual ditolak. Turunkan supaya klik berikutnya jadi
                # tepi naik yang baru (aturan ladder nomor 3).
                terbuka = di_manual < len(self.inputs) and self.inputs[di_manual]
                if not terbuka:
                    with self._piston_lock:
                        self._piston_requested = minta = False
                    logger.warning("PLC tidak membenarkan piston terbuka — permintaan dibatalkan")
            if minta != self._piston_written:
                writes[coil_manual] = minta
                self._piston_written = minta
                if minta:
                    self._piston_deadline = now + 2.0

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
        tengah pulse (200ms ON dalam siklus 400 ms, 2 tick) kalau tidak begini
        meninggalkan coil OK atau NG nyangkut ON sampai watchdog ODOT menyerah.
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
