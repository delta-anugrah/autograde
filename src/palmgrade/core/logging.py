"""Satu cara memasang logging untuk line DAN konsol (batch 3.1 + 3.4).

Sebelum ini konsol tidak pernah memasangnya: root logger tanpa handler keluaran
dan level bawaan WARNING, jadi INFO konsol dibuang, WARNING/ERROR-nya cuma ke
SQLite (tab Log) dan tidak pernah ke `docker logs`, dan exception 500 yang dicatat
uvicorn di `uvicorn.error` berhenti di handler uvicorn sendiri (`propagate=False`
di logger `uvicorn`), tidak pernah sampai tab Log.

Tiap baris sekarang membawa:

- jam dengan penanda zona (`2026-09-30T14:03:07.123+07:00`): zona pabrik
  (`FACTORY_TZ`), atau UTC yang ditulis `+00:00` kalau zonanya kosong atau salah.
  Sengaja lewat formatter, BUKAN `TZ` di environment: `TZ` mengubah
  `datetime.now()` telanjang di seluruh proses dan memindahkan folder hasil
  (CLAUDE.md aturan 8);
- konteks: kode line (`line-2`) atau `console`, supaya log tiga line yang
  digabung tetap bisa dipisah;
- level dari `LOG_LEVEL` (bawaan INFO). `LOG_LEVEL` cuma mengatur keluaran proses;
  handler tambahan (SQLite tab Log) tetap menerima WARNING dan ERROR apa pun
  nilainya, karena tab Log adalah yang dibaca support berbulan-bulan kemudian.

Logger uvicorn diarahkan ke root, jadi access log dan galat uvicorn memakai format
yang sama dan `uvicorn.error` sampai ke handler tambahan. Access log polling yang
sukses dibisukan (`core/log_akses.py`). Logger `httpx`/`httpcore` dibatasi WARNING:
alamat permintaan (webhook Discord yang rahasia, polling status tiap detik) tidak
pernah tertulis.

Nilai yang salah tidak pernah menahan boot: jatuh ke bawaan dengan satu WARNING.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .log_akses import SaringAksesPolling

logger = logging.getLogger(__name__)

#: Konteks tetap untuk baris log konsol (line memakai kode line-nya sendiri).
KONTEKS_KONSOL = "console"

FORMAT_LOG = "%(asctime)s | %(levelname)s | %(line_code)s | %(name)s | %(message)s"

_LEVEL_SAH = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

#: Logger milik uvicorn. `uvicorn` dan `uvicorn.access` punya handler sendiri dan
#: `propagate=False` di konfigurasi bawaan uvicorn; `uvicorn.error` naik ke `uvicorn`.
_LOGGER_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")

#: Klien HTTP yang menulis tiap permintaan di INFO lengkap dengan alamatnya
#: (`HTTP Request: POST <url> ...`): alamat webhook Discord adalah rahasia, dan
#: polling status tiga line tiap detik membanjiri `docker logs`. Dibatasi WARNING
#: apa pun `LOG_LEVEL`-nya; galat koneksinya tetap tertulis.
_LOGGER_KLIEN_HTTP = ("httpx", "httpcore")


def level_dari_teks(teks: str | None) -> tuple[int, bool]:
    """`LOG_LEVEL` jadi level logging. `(level, sah)`; kosong = INFO dan tetap sah."""
    bersih = (teks or "").strip().upper()
    if not bersih:
        return logging.INFO, True
    level = _LEVEL_SAH.get(bersih)
    return (logging.INFO, False) if level is None else (level, True)


def zona_dari_nama(nama: str | None) -> tuple[tzinfo, bool]:
    """Nama zona jadi tzinfo. `(zona, sah)`; kosong = UTC dan tetap sah."""
    bersih = (nama or "").strip()
    if not bersih:
        return UTC, True
    try:
        return ZoneInfo(bersih), True
    except (ZoneInfoNotFoundError, ValueError):
        return UTC, False


class FormatterPabrik(logging.Formatter):
    """Format tetap, jam ISO 8601 dengan offset zona yang diberikan."""

    def __init__(self, zona: tzinfo) -> None:
        super().__init__(FORMAT_LOG)
        self._zona = zona

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created, self._zona).isoformat(timespec="milliseconds")


class FilterKonteks(logging.Filter):
    """Tempelkan `line_code` ke record yang belum punya (record dari line lain tetap)."""

    def __init__(self, konteks: str) -> None:
        super().__init__()
        self.konteks = konteks

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "line_code", None):
            record.line_code = self.konteks
        return True


class _HandlerKeluaranProses(logging.StreamHandler):
    """Ke stderr proses (yang dibaca `docker logs`), sama dengan `basicConfig` dulu.

    Aliran dibaca SAAT menulis, bukan saat dipasang: yang menggantinya (pytest,
    `contextlib.redirect_stderr`) tidak meninggalkan handler yang menulis ke berkas
    yang sudah ditutup.
    """

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stderr

    @stream.setter
    def stream(self, _nilai) -> None:
        pass


class PemasanganLog:
    """Apa yang dipasang `configure_logging`, supaya bisa dilepas utuh lagi."""

    def __init__(self) -> None:
        self.handler: list[logging.Handler] = []
        self._level_root_semula = logging.getLogger().level
        self._uvicorn_semula: dict[str, tuple[list[logging.Handler], bool]] = {}
        self._level_klien_http_semula: dict[str, int] = {}
        self._saring = SaringAksesPolling()
        self._dilepas = False

    def _ambil_alih_uvicorn(self) -> None:
        for nama in _LOGGER_UVICORN:
            lg = logging.getLogger(nama)
            self._uvicorn_semula[nama] = (list(lg.handlers), lg.propagate)
            lg.handlers = []
            lg.propagate = True
        logging.getLogger("uvicorn.access").addFilter(self._saring)

    def _batasi_klien_http(self) -> None:
        for nama in _LOGGER_KLIEN_HTTP:
            lg = logging.getLogger(nama)
            self._level_klien_http_semula[nama] = lg.level
            lg.setLevel(logging.WARNING)

    def lepas(self) -> None:
        """Kembalikan root, logger uvicorn, dan klien HTTP seperti sebelum dipasang. Aman diulang."""
        global _aktif
        if self._dilepas:
            return
        self._dilepas = True
        root = logging.getLogger()
        for handler in self.handler:
            root.removeHandler(handler)
        root.setLevel(self._level_root_semula)
        for nama, (handlers, propagate) in self._uvicorn_semula.items():
            lg = logging.getLogger(nama)
            lg.handlers = handlers
            lg.propagate = propagate
        logging.getLogger("uvicorn.access").removeFilter(self._saring)
        for nama, level in self._level_klien_http_semula.items():
            logging.getLogger(nama).setLevel(level)
        if _aktif is self:
            _aktif = None


_aktif: PemasanganLog | None = None


def configure_logging(
    *,
    konteks: str,
    zona: str | None = None,
    level: str | None = None,
    handler_tambahan: Sequence[logging.Handler] = (),
) -> PemasanganLog:
    """Pasang keluaran proses + handler tambahan di root. Memanggil lagi = mengganti.

    `konteks`: kode line (`settings.line_code`) atau `KONTEKS_KONSOL`. `zona`: biasanya
    `FACTORY_TZ`. `level`: teks `LOG_LEVEL`. `handler_tambahan`: mis. `SqliteLogHandler`
    tab Log; levelnya milik handler itu sendiri, tidak diatur `LOG_LEVEL`.
    """
    global _aktif
    if _aktif is not None:
        _aktif.lepas()
    root = logging.getLogger()
    # Keluaran proses cuma boleh satu. Yang yatim (pemasangan lama yang sudah dilepas
    # tapi handlernya dikembalikan pemanggil lain, mis. test yang memulihkan daftar
    # handler root) dibuang juga, kalau tidak tiap baris tertulis dua kali.
    for handler in list(root.handlers):
        if isinstance(handler, _HandlerKeluaranProses):
            root.removeHandler(handler)

    nilai_level, level_sah = level_dari_teks(level)
    nilai_zona, zona_sah = zona_dari_nama(zona)
    debug_model = os.getenv("DEBUG_MODEL_OUTPUT", "").lower() in ("1", "true")

    pasang = PemasanganLog()
    formatter = FormatterPabrik(nilai_zona)
    konteks_filter = FilterKonteks(konteks)
    keluaran = _HandlerKeluaranProses()
    # DEBUG_MODEL_OUTPUT menyalakan DEBUG di satu logger (di bawah); handler keluaran
    # harus ikut mau menerima DEBUG, logger lain tetap disaring level root.
    keluaran.setLevel(logging.DEBUG if debug_model else nilai_level)
    for handler in (keluaran, *handler_tambahan):
        if handler.formatter is None:
            handler.setFormatter(formatter)
        handler.addFilter(konteks_filter)
        root.addHandler(handler)
        pasang.handler.append(handler)
    # Root tidak pernah di atas WARNING: tab Log tetap menerima WARNING walau
    # LOG_LEVEL=ERROR membuat keluaran proses cuma menampilkan ERROR.
    root.setLevel(min(nilai_level, logging.WARNING))
    pasang._ambil_alih_uvicorn()
    pasang._batasi_klien_http()
    _aktif = pasang

    if debug_model:
        # Nama logger diturunkan dari paket ini sendiri, bukan ditulis tangan.
        # Dulu barisnya `"src.palmgrade.workers..."`, padahal paketnya dimuat
        # sebagai `palmgrade...` (`src` itu root path, bukan bagian nama modul),
        # jadi level DEBUG mendarat di logger yang tidak pernah dipakai siapa pun
        # dan `DEBUG_MODEL_OUTPUT=true` tidak menghasilkan satu baris pun.
        # Diam-diam, karena menyetel level logger yang tidak ada bukan error.
        paket = __name__.rsplit(".", 2)[0]  # palmgrade.core.logging -> palmgrade
        logging.getLogger(f"{paket}.workers.frame_processing_worker").setLevel(logging.DEBUG)
    if not level_sah:
        logger.warning(
            "LOG_LEVEL=%r tidak dikenal (pilih DEBUG, INFO, WARNING, ERROR, atau CRITICAL); memakai INFO",
            level,
        )
    if not zona_sah:
        logger.warning("FACTORY_TZ=%r bukan zona waktu yang dikenal; jam log memakai UTC (+00:00)", zona)
    return pasang
