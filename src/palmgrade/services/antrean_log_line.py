"""Pintu log line ke disk yang tidak pernah membuat pemanggilnya menunggu (batch 3.2).

`SqliteLogHandler` (`core/log_sink.py`) memanggil `write()` di thread yang menulis
log, dan di line itu bisa thread deteksi: `CaptureSaveWorker.submit()` menulis ERROR
tepat saat disk lambat. Aturan 1b melarang deteksi menunggu disk, jadi `write()` di sini
cuma menaruh kejadian di antrean memori; thread penulis sendiri yang menguras ke
`LogLineStore` tiap ~0,2 detik.

Harga yang diterima: kejadian yang ditulis beberapa ratus milidetik sebelum proses
mati mendadak (SIGKILL, listrik) bisa hilang. Restart dari konsol dan SIGTERM tidak
kehilangannya: urutan tutup line makan waktu jauh lebih lama dari satu kurasan.
Antrean penuh (1000 kejadian yang belum sempat ditulis) membuang yang paling lama
dan menghitungnya, bukan menahan pemanggil.
"""
from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Protocol

from ..core.log_sink import install_log_sink
from ..domain.log_line import EntriLog
from ..repositories.log_line_repository import NAMA_DB_LOG_LINE, LogLineStore

logger = logging.getLogger(__name__)

KAPASITAS_ANTREAN = 1000
JEDA_KURAS_S = 0.2
NAMA_THREAD = "log_line"


class _PenyimpanLog(Protocol):
    def tulis_banyak(self, entri: list[EntriLog], *, dibuang_antrean: int = 0) -> None: ...


class AntreanLogLine:
    def __init__(
        self, store: _PenyimpanLog, *, kapasitas: int = KAPASITAS_ANTREAN, jeda_s: float = JEDA_KURAS_S
    ) -> None:
        self._store = store
        self._kapasitas = kapasitas
        self._jeda_s = jeda_s
        self._antre: deque[EntriLog] = deque()
        self._kunci = threading.Lock()
        self._ada = threading.Event()
        self._dibuang = 0
        self._sudah_mengeluh = False

    def write(
        self, level: str, source: str, message: str, detail: str | None, *, now: float
    ) -> None:
        """Bentuk `_LogSink`. Tidak pernah menyentuh disk dan tidak pernah melempar."""
        with self._kunci:
            self._taruh(EntriLog(level, source, message, detail, now))
        self._ada.set()

    def _taruh(self, entri: EntriLog) -> None:
        if len(self._antre) >= self._kapasitas:
            self._antre.popleft()
            self._dibuang += 1
        self._antre.append(entri)

    def kuras(self) -> int:
        """Tulis semua yang menunggu dalam satu transaksi. Mengembalikan jumlahnya.

        Gagal menulis (disk penuh, berkas rusak) mengembalikan kejadiannya ke depan
        antrean dan mengeluh SEKALI ke stderr: log yang rusak tidak boleh menjatuhkan
        line, dan tidak boleh diam selamanya juga.
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
        except Exception:  # noqa: BLE001, lihat docstring
            with self._kunci:
                baru = list(self._antre)
                self._antre.clear()
                self._dibuang += dibuang
                for e in batch + baru:
                    self._taruh(e)
            if not self._sudah_mengeluh:
                self._sudah_mengeluh = True
                print(
                    "log line could not be written; the console Log tab will miss this line",
                    file=sys.stderr,
                )
            return 0
        return len(batch)

    def jalan(self, berhenti: threading.Event) -> None:
        """Loop thread penulis. Tidak pernah keluar karena galat."""
        while not berhenti.is_set():
            self._ada.wait(timeout=1.0)
            self._ada.clear()
            berhenti.wait(self._jeda_s)
            self.kuras()
        self.kuras()

    def mulai(self) -> threading.Event:
        """Nyalakan thread penulis (daemon). Mengembalikan saklar hentinya (untuk test)."""
        berhenti = threading.Event()
        threading.Thread(target=self.jalan, args=(berhenti,), daemon=True, name=NAMA_THREAD).start()
        return berhenti


def pasang_log_line(folder_db: Path) -> LogLineStore | None:
    """Buka log line, nyalakan penulisnya, dan pasang handlernya di root logger.

    `None` kalau berkasnya tidak bisa dibuka: line tetap jalan tanpa log di disk,
    `GET /internal/log` menjawab 503, dan alasannya ada di `docker logs`.
    """
    try:
        store = LogLineStore(folder_db / NAMA_DB_LOG_LINE)
    except Exception:  # noqa: BLE001, log yang rusak tidak boleh menjatuhkan line
        logger.exception("Log line di %s tidak bisa dibuka; tab Log konsol tidak menerima log line ini", folder_db)
        return None
    antrean = AntreanLogLine(store)
    antrean.mulai()
    install_log_sink(antrean)
    return store
