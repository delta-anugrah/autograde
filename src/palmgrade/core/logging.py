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

#: Paket kita (`palmgrade.core.logging` -> `palmgrade`). `LOG_LEVEL=DEBUG` cuma
#: berlaku di sini: DEBUG pustaka lain (botocore menulis header bertanda tangan
#: berisi access key id) tidak pernah dinyalakan.
_PAKET = __name__.rsplit(".", 2)[0]

#: Logger baris `[MODEL]` yang dinyalakan `DEBUG_MODEL_OUTPUT`. Diturunkan dari
#: paket ini sendiri, bukan ditulis tangan: dulu barisnya `"src.palmgrade..."`,
#: padahal paketnya dimuat sebagai `palmgrade...`, jadi level DEBUG mendarat di
#: logger yang tidak pernah dipakai siapa pun, diam-diam.
_LOGGER_MODEL = f"{_PAKET}.workers.frame_processing_worker"


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
    except (ZoneInfoNotFoundError, ValueError, OSError):
        # OSError: nama folder zona (`Asia`) lewat paket `tzdata` = IsADirectoryError.
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


class _SaringLevelKeluaran(logging.Filter):
    """Keluaran proses di `DEBUG_MODEL_OUTPUT`: level `LOG_LEVEL`, kecuali baris model.

    Handler-nya harus mau menerima DEBUG untuk baris `[MODEL]`, tapi logger lain yang
    levelnya disetel sendiri (uvicorn.access INFO) tetap disaring `LOG_LEVEL`.
    """

    def __init__(self, level: int, logger_lolos: str) -> None:
        super().__init__()
        self._level = level
        self._logger_lolos = logger_lolos

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self._level or record.name == self._logger_lolos


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

    def __init__(self, filter_konteks: FilterKonteks) -> None:
        self.handler: list[logging.Handler] = []
        self._level_root_semula = logging.getLogger().level
        self._uvicorn_semula: dict[str, tuple[list[logging.Handler], bool]] = {}
        #: Level logger yang diubah pemasangan ini (klien HTTP, paket, logger model).
        self._level_semula: dict[str, int] = {}
        self._saring = SaringAksesPolling()
        self._filter_konteks = filter_konteks
        #: Handler yang formatter-nya dipasang di sini (bukan milik pemanggil).
        self._formatter_dipasang: list[logging.Handler] = []
        self._dilepas = False

    def _pasang_handler(self, handler: logging.Handler, formatter: logging.Formatter) -> None:
        if handler.formatter is None:
            handler.setFormatter(formatter)
            self._formatter_dipasang.append(handler)
        handler.addFilter(self._filter_konteks)
        logging.getLogger().addHandler(handler)
        self.handler.append(handler)

    def _setel_level(self, nama: str, level: int) -> None:
        lg = logging.getLogger(nama)
        self._level_semula.setdefault(nama, lg.level)
        lg.setLevel(level)

    def _ambil_alih_uvicorn(self) -> None:
        for nama in _LOGGER_UVICORN:
            lg = logging.getLogger(nama)
            self._uvicorn_semula[nama] = (list(lg.handlers), lg.propagate)
            lg.handlers = []
            lg.propagate = True
        logging.getLogger("uvicorn.access").addFilter(self._saring)

    def _batasi_klien_http(self) -> None:
        # max: level yang lebih ketat dari pemanggil (ERROR) tetap dihormati.
        for nama in _LOGGER_KLIEN_HTTP:
            self._setel_level(nama, max(logging.getLogger(nama).level, logging.WARNING))

    def lepas(self) -> None:
        """Kembalikan root, logger yang diubah, dan handler pemanggil seperti semula. Aman diulang."""
        global _aktif
        if self._dilepas:
            return
        self._dilepas = True
        root = logging.getLogger()
        for handler in self.handler:
            root.removeHandler(handler)
            handler.removeFilter(self._filter_konteks)
        for handler in self._formatter_dipasang:
            handler.setFormatter(None)
        root.setLevel(self._level_root_semula)
        for nama, (handlers, propagate) in self._uvicorn_semula.items():
            lg = logging.getLogger(nama)
            lg.handlers = handlers
            lg.propagate = propagate
        logging.getLogger("uvicorn.access").removeFilter(self._saring)
        for nama, level in self._level_semula.items():
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

    pasang = PemasanganLog(FilterKonteks(konteks))
    formatter = FormatterPabrik(nilai_zona)
    keluaran = _HandlerKeluaranProses()
    if debug_model:
        # Baris `[MODEL]` (DEBUG) harus lolos; yang lain tetap disaring LOG_LEVEL.
        keluaran.setLevel(logging.DEBUG)
        keluaran.addFilter(_SaringLevelKeluaran(nilai_level, _LOGGER_MODEL))
    else:
        keluaran.setLevel(nilai_level)
    for handler in (keluaran, *handler_tambahan):
        pasang._pasang_handler(handler, formatter)
    # Root di antara INFO dan WARNING: tidak pernah di atas WARNING (tab Log tetap
    # menerima WARNING walau LOG_LEVEL=ERROR), tidak pernah di bawah INFO (DEBUG
    # pustaka pihak ketiga tidak pernah dinyalakan).
    root.setLevel(min(max(nilai_level, logging.INFO), logging.WARNING))
    if nilai_level < logging.INFO:
        pasang._setel_level(_PAKET, nilai_level)
    if debug_model:
        pasang._setel_level(_LOGGER_MODEL, logging.DEBUG)
    pasang._ambil_alih_uvicorn()
    pasang._batasi_klien_http()
    _aktif = pasang
    if not level_sah:
        logger.warning(
            "LOG_LEVEL=%r tidak dikenal (pilih DEBUG, INFO, WARNING, ERROR, atau CRITICAL); memakai INFO",
            level,
        )
    if not zona_sah:
        logger.warning("FACTORY_TZ=%r bukan zona waktu yang dikenal; jam log memakai UTC (+00:00)", zona)
    return pasang
