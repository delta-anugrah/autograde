"""Pintu log line ke disk yang tidak pernah membuat pemanggilnya menunggu (batch 3.2).

`SqliteLogHandler` (`core/log_sink.py`) memanggil `write()` di thread yang menulis
log, dan di line itu bisa thread deteksi: `CaptureSaveWorker.submit()` menulis ERROR
tepat saat disk lambat. Aturan 1b melarang deteksi menunggu disk, jadi `write()` di sini
cuma menaruh kejadian di antrean memori; thread penulis sendiri yang menguras ke
`LogLineStore` tiap ~0,2 detik.

Keluar biasa (SIGTERM lewat uvicorn, `sys.exit` saat startup gagal) menguras sisa
antrean lewat `atexit`, jadi galat terakhir sebelum line mati tetap sampai ke tab Log;
justru itu yang dicari support saat line berputar gagal start. Restart dan hapus data
dari konsol keluar lewat `os._exit` (`penutup_line.keluar_nanti`), yang melewati
`atexit`: `main.py` mendaftarkan `PenulisLogLine.hentikan` ke `sebelum_keluar` penutup,
jadi antreannya dikuras juga di sana. Yang tetap bisa hilang: kejadian ~0,2 detik
terakhir saat proses mati tanpa lewat keduanya, yaitu SIGKILL dan listrik.
Antrean penuh (1000 kejadian yang belum sempat ditulis) membuang yang paling lama
dan menghitungnya, bukan menahan pemanggil.

Disk yang menolak SEMUA tulisan (penuh, `state/` jadi read-only) tidak dicoba tanpa jeda:
sesudah kurasan yang tidak menulis apa pun, thread penulis tidur 1 detik berlipat sampai
30 detik sebelum mencoba lagi. Tanpa ini tiap ~0,2 detik satu batch gagal plus satu
transaksi gagal per kejadian menunggu, di PC yang disknya memang sedang bermasalah.
"""
from __future__ import annotations

import atexit
import logging
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..core.log_sink import SqliteLogHandler, install_log_sink
from ..domain.log_line import PANJANG_SUMBER_MAKS, EntriLog, potong_detail, potong_pesan
from ..repositories.log_line_repository import NAMA_DB_LOG_LINE, LogLineStore

logger = logging.getLogger(__name__)

KAPASITAS_ANTREAN = 1000
JEDA_KURAS_S = 0.2
#: Menunggu thread penulis selesai saat berhenti. Kecil: SIGTERM punya anggaran
#: 10 detik `docker stop`, dan urutan tutup line sudah memakai sampai 9 detik.
BATAS_BERHENTI_S = 0.5
NAMA_THREAD = "log_line"
#: Jeda coba lagi sesudah kurasan yang tidak menulis apa pun: mulai 1 detik, berlipat, maks 30.
JEDA_GAGAL_AWAL_S = 1.0
JEDA_GAGAL_MAKS_S = 30.0


class _PenyimpanLog(Protocol):
    def tulis_banyak(self, entri: list[EntriLog], *, dibuang_antrean: int = 0) -> None: ...


def _aman(teks: object) -> str:
    """Teks yang pasti bisa di-encode UTF-8: surrogate (nama berkas bukan UTF-8) jadi `\\udcff`."""
    return str(teks).encode("utf-8", "backslashreplace").decode("utf-8")


def _entri(level: str, source: str, message: str, detail: str | None, now: float) -> EntriLog:
    """Dipotong di sini, sebelum antre: batas 1000 kejadian juga membatasi memori."""
    return EntriLog(
        level,
        _aman(source)[:PANJANG_SUMBER_MAKS],
        potong_pesan(_aman(message)),
        potong_detail(_aman(detail)) if detail is not None else None,
        now,
    )


def _ke_stderr(pesan: str) -> None:
    # stderr yang tertutup atau hilang tidak boleh mematikan thread penulis.
    try:
        print(pesan, file=sys.stderr)
    except (OSError, ValueError):
        pass


class AntreanLogLine:
    def __init__(
        self, store: _PenyimpanLog, *, kapasitas: int = KAPASITAS_ANTREAN, jeda_s: float = JEDA_KURAS_S
    ) -> None:
        self._store = store
        self._kapasitas = kapasitas
        self._jeda_s = jeda_s
        self._antre: deque[EntriLog] = deque()
        # RLock: finalizer atau signal handler yang menulis log di tengah `write()`
        # thread yang sama tidak boleh membuat thread deteksi macet selamanya.
        self._kunci = threading.RLock()
        self._ada = threading.Event()
        self._dibuang = 0
        self._sudah_mengeluh = False
        self._thread: threading.Thread | None = None
        #: Tidur tambahan thread penulis sesudah kurasan yang gagal total. 0 = sehat.
        self.jeda_gagal_s = 0.0

    def write(
        self, level: str, source: str, message: str, detail: str | None, *, now: float
    ) -> None:
        """Bentuk `_LogSink`. Tidak pernah menyentuh disk dan tidak pernah melempar."""
        try:
            entri: EntriLog | None = _entri(level, source, message, detail, now)
        except Exception:  # noqa: BLE001, pemanggilnya bisa thread deteksi
            entri = None
        with self._kunci:
            if entri is None:
                self._dibuang += 1
            else:
                self._taruh(entri)
        self._ada.set()

    def _taruh(self, entri: EntriLog) -> None:
        if len(self._antre) >= self._kapasitas:
            self._antre.popleft()
            self._dibuang += 1
        self._antre.append(entri)

    def kuras(self) -> int:
        """Tulis semua yang menunggu dalam satu transaksi. Mengembalikan jumlah yang tertulis.

        Batch yang gagal ditulis ulang satu per satu: kejadian yang gagal sendirian
        dibuang dan dihitung, supaya satu kejadian racun tidak menyandera yang lain.
        Kalau semuanya gagal, disknya yang rusak: kejadiannya kembali ke depan antrean
        dan penulis mengeluh SEKALI per gangguan ke stderr, dengan sebabnya.
        """
        with self._kunci:
            batch = list(self._antre)
            dibuang = self._dibuang
            self._antre.clear()
            self._dibuang = 0
        if not batch and not dibuang:
            return 0
        try:
            self._store.tulis_banyak(batch, dibuang_antrean=dibuang)
        except Exception as exc:  # noqa: BLE001, lihat docstring
            return self._tulis_satu_per_satu(batch, dibuang, exc)
        self._sudah_mengeluh = False
        self.jeda_gagal_s = 0.0
        return len(batch)

    def _tulis_satu_per_satu(self, batch: list[EntriLog], dibuang: int, galat: Exception) -> int:
        tertulis = 0
        racun = 0
        for e in batch:
            try:
                self._store.tulis_banyak([e])
            except Exception as exc:  # noqa: BLE001
                racun += 1
                galat = exc
            else:
                tertulis += 1
        if not tertulis:
            self._kembalikan(batch, dibuang)
            self._mengeluh(galat)
            self.jeda_gagal_s = min(max(self.jeda_gagal_s * 2, JEDA_GAGAL_AWAL_S), JEDA_GAGAL_MAKS_S)
            return 0
        self._sudah_mengeluh = False
        self.jeda_gagal_s = 0.0
        if racun:
            _ke_stderr(
                f"log line dropped {racun} entries that could not be written:"
                f" {type(galat).__name__}: {galat}"
            )
        try:
            self._store.tulis_banyak([], dibuang_antrean=dibuang + racun)
        except Exception:  # noqa: BLE001, hitungannya dicoba lagi di kurasan berikut
            with self._kunci:
                self._dibuang += dibuang + racun
        return tertulis

    def _kembalikan(self, batch: list[EntriLog], dibuang: int) -> None:
        with self._kunci:
            baru = list(self._antre)
            self._antre.clear()
            self._dibuang += dibuang
            for e in batch + baru:
                self._taruh(e)

    def _mengeluh(self, galat: Exception) -> None:
        if self._sudah_mengeluh:
            return
        self._sudah_mengeluh = True
        _ke_stderr(
            "log line could not be written; the console Log tab will miss this line:"
            f" {type(galat).__name__}: {galat}"
        )

    def jalan(self, berhenti: threading.Event) -> None:
        """Loop thread penulis. Tidak pernah keluar karena galat."""
        while not berhenti.is_set():
            self._ada.wait(timeout=1.0)
            self._ada.clear()
            berhenti.wait(self._jeda_s)
            self.kuras()
            if self.jeda_gagal_s and not berhenti.is_set():
                berhenti.wait(self.jeda_gagal_s)
        self.kuras()

    def mulai(self) -> threading.Event:
        """Nyalakan thread penulis (daemon). Mengembalikan saklar hentinya."""
        berhenti = threading.Event()
        self._thread = threading.Thread(
            target=self.jalan, args=(berhenti,), daemon=True, name=NAMA_THREAD
        )
        self._thread.start()
        return berhenti

    def hentikan(self, berhenti: threading.Event, *, batas_s: float = BATAS_BERHENTI_S) -> bool:
        """Hentikan penulis dan tulis sisanya. True = thread penulis sudah berhenti.

        Thread yang macet di disk lambat tidak ditunggu lewat `batas_s` (dan sisanya
        tidak dikuras dari sini: kurasan kedua akan antre di kunci store yang sama).
        """
        berhenti.set()
        self._ada.set()
        if self._thread is not None:
            self._thread.join(batas_s)
            if self._thread.is_alive():
                return False
        self.kuras()
        return True


@dataclass
class PenulisLogLine:
    """Log line yang terpasang: store untuk `GET /internal/log`, plus kendali berhentinya."""

    store: LogLineStore
    antrean: AntreanLogLine
    handler: SqliteLogHandler
    berhenti: threading.Event

    def __post_init__(self) -> None:
        atexit.register(self._saat_keluar)

    def _saat_keluar(self) -> None:
        self.antrean.hentikan(self.berhenti)

    def hentikan(self) -> bool:
        """Copot handler dari root logger, hentikan penulis, tulis sisanya.

        Dipanggil test, dan `penutup_line.keluar_nanti` tepat sebelum `os._exit`.
        Berbatas waktu (`BATAS_BERHENTI_S`), jadi tidak bisa menahan restart.
        """
        logging.getLogger().removeHandler(self.handler)
        atexit.unregister(self._saat_keluar)
        return self.antrean.hentikan(self.berhenti)


def pasang_penulis_log_line(folder_db: Path) -> PenulisLogLine | None:
    """Buka log line, nyalakan penulisnya, pasang handlernya di root logger, dan
    daftarkan pengurasan saat proses keluar.

    `None` kalau berkasnya tidak bisa dibuka: line tetap jalan tanpa log di disk,
    `GET /internal/log` menjawab 503, dan alasannya ada di `docker logs`.
    """
    try:
        store = LogLineStore(folder_db / NAMA_DB_LOG_LINE)
    except Exception:  # noqa: BLE001, log yang rusak tidak boleh menjatuhkan line
        logger.exception("Log line di %s tidak bisa dibuka; tab Log konsol tidak menerima log line ini", folder_db)
        return None
    antrean = AntreanLogLine(store)
    berhenti = antrean.mulai()
    return PenulisLogLine(store, antrean, install_log_sink(antrean), berhenti)


def pasang_log_line(folder_db: Path) -> LogLineStore | None:
    """Bentuk pendek: cuma store-nya, tanpa kendali berhenti.

    `main.py` TIDAK memakai ini: dia memegang `PenulisLogLine` dari
    `pasang_penulis_log_line` supaya antrean bisa dikuras sebelum `os._exit`.
    """
    penulis = pasang_penulis_log_line(folder_db)
    return penulis.store if penulis is not None else None
