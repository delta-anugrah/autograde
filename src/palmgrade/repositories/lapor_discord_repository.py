"""Antrean lapor Discord di disk konsol (batch 3.5): galat menunggu → pesan siap kirim.

Dua tahap, satu berkas (`state/lapor_discord.db`), pola antrean yang sama dengan
outbox (WAL, `synchronous=FULL`, satu kunci):

1. `galat_menunggu`: satu baris per jenis galat, hitungannya naik terus sampai
   ringkasan berikutnya disusun. Diisi handler ERROR konsol (`write`) dan ERROR line
   yang ditarik (`antre_line`).
2. `kiriman`: isi pesan Discord yang sudah disusun, dihapus HANYA saat Discord
   menjawab 2xx. Penyusunan memindah tahap 1 ke tahap 2 dalam SATU transaksi
   (`BEGIN IMMEDIATE` sebelum SELECT, jadi tulisan dari koneksi lain di antara SELECT
   dan DELETE menunggu, bukan menyelinap lalu terhapus tanpa pernah ikut kelompok),
   jadi listrik mati di tengahnya tidak menghilangkan atau menggandakan galat YANG
   SUDAH masuk sebelum `susun` mulai.

   Jaminannya "sampai konsol" (line ke konsol, konsol ke `galat_menunggu`), BUKAN
   "sampai Discord": begitu Discord sudah menjawab 2xx tapi proses mati atau koneksi
   putus SEBELUM `tandai_terkirim` sempat jalan, pesan yang sama terkirim lagi saat
   worker mencoba ulang (webhook Discord tidak punya kunci idempotensi). Ini paling
   sedikit sekali (at-least-once), bukan tepat sekali.

⚠️ **`susun_pesan` TIDAK BOLEH mencatat log lewat handler yang disambungkan ke store
ini** (`write`/`antre_line`). `susun` memegang `self._lock` (non-reentrant) sepanjang
pemanggilan `susun_pesan`; thread yang sama mencoba masuk lagi lewat `write` akan
mengunci dirinya sendiri selamanya, dan karena lock yang sama dipakai SEMUA method,
thread lain (termasuk event loop) yang lalu memanggil method store mana pun ikut
menggantung. Penjaga re-entry di `_antre` cuma menutup kasus THREAD YANG SAMA: entri
yang masuk lagi dari dalam `susun_pesan` dilewati (bukan menunggu), jadi hilang dari
digest ini (baris log lain, kalau ada, tetap menyimpannya). Kasus DUA THREAD
(thread lain sudah di dalam `handle()` handler lapor, menunggu `self._lock`, sementara
`susun_pesan` mencatat ERROR dan menunggu kunci handler itu) tidak ditutup guard ini:
yang mencegahnya aturan "`susun_pesan` tidak mencatat log" di atas DAN handler lapor
yang sengaja tanpa kunci handler (`services/lapor_discord.pasang_handler_lapor`; store
ini sudah menyerialkan dirinya sendiri).

Berkas milik konsol (`test_semua_berkas_db_di_state_digolongkan`). Danger Zone tidak
mengosongkannya: isinya laporan yang belum keluar, bukan data transaksi.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..domain.digest_galat import (
    BATAS_KELOMPOK_MENUNGGU,
    PESAN_LAIN,
    SIDIK_LAIN,
    KelompokGalat,
    sidik_digest,
)

logger = logging.getLogger(__name__)

#: Batas ukuran `message`/`source` yang disimpan (karakter). `sidik_digest` tetap
#: memakai teks PENUH sebelum dipotong (M3): dua galat yang cuma beda di ekor yang
#: panjang tidak boleh diam-diam disatukan sidiknya gara-gara pemotongan ini.
_MASUK_CHARS = 4000

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS galat_menunggu (
    sidik        TEXT PRIMARY KEY,
    level        TEXT NOT NULL,
    source       TEXT NOT NULL,
    line_code    TEXT,
    message      TEXT NOT NULL,
    pertama_at   REAL NOT NULL,
    terakhir_at  REAL NOT NULL,
    jumlah       INTEGER NOT NULL,
    masuk_at     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kiriman (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    isi          TEXT NOT NULL,
    dibuat_at    REAL NOT NULL,
    percobaan    INTEGER NOT NULL DEFAULT 0,
    galat        TEXT,
    galat_at     REAL
);
CREATE TABLE IF NOT EXISTS keadaan (
    kunci  TEXT PRIMARY KEY,
    nilai  TEXT NOT NULL
);
"""
_GALAT_CHARS = 300


class _GalatLine(Protocol):
    level: str
    source: str
    line_code: str
    message: str
    pertama_at: float
    terakhir_at: float
    tambah: int


@dataclass(frozen=True)
class Kiriman:
    id: int
    isi: str
    percobaan: int


class LaporDiscordStore:
    def __init__(self, db_path: Path, *, jam: Callable[[], float] = time.time) -> None:
        self._jam = jam
        self._lock = threading.Lock()
        #: Thread yang SEDANG memegang `self._lock` (I2). `threading.Lock` tidak
        #: menyimpan pemiliknya sendiri, jadi dicatat manual, cuma untuk mendeteksi
        #: re-entry, bukan untuk sinkronisasi (itu tetap tugas `self._lock`).
        self._pemegang_lock: int | None = None
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ── tahap 1: galat menunggu ──────────────────────────────────────────

    def write(
        self, level: str, source: str, message: str, detail: str | None, *, now: float
    ) -> None:
        """Bentuk `_LogSink` untuk handler ERROR konsol. Traceback tidak ikut keluar pabrik.

        M5: level di bawah ERROR diabaikan. Handler yang memasang store ini seharusnya
        sudah menyaring level, ini cuma pertahanan lapis kedua di store sendiri.
        """
        if level != "ERROR":
            return
        self._antre([KelompokGalat(level, source, None, message, now, now, 1)])

    def antre_line(self, galat: Iterable[_GalatLine]) -> None:
        """ERROR line yang baru ditarik konsol (`TarikLogLineWorker`)."""
        self._antre(
            [
                KelompokGalat(g.level, g.source, g.line_code, g.message, g.pertama_at, g.terakhir_at, g.tambah)
                for g in galat
            ]
        )

    def _antre(self, kelompok: list[KelompokGalat]) -> None:
        if self._pemegang_lock == threading.get_ident():
            # I2: thread ini sedang di dalam `susun` (memegang `self._lock`) dan
            # sekarang mencoba menulis lagi lewat handler log yang disambungkan ke
            # store yang sama. Mengunci lagi di sini = deadlock selamanya. Lewati
            # entrinya (galat masih tercatat di baris log lain kalau ada) daripada
            # menggantungkan seluruh proses.
            logger.warning(
                "LaporDiscordStore: entri dilewati, dipanggil dari dalam susun_pesan"
                " (thread yang sama sedang memegang lock; lihat docstring modul)"
            )
            return
        now = self._jam()
        with self._lock, self._db:
            self._pemegang_lock = threading.get_ident()
            try:
                for k in kelompok:
                    self._antre_satu(k, now)
            finally:
                self._pemegang_lock = None

    def _antre_satu(self, k: KelompokGalat, now: float) -> None:
        # M3: sidik dihitung dari teks PENUH sebelum dipotong, supaya dua galat yang
        # cuma beda di ekor yang panjang tidak diam-diam disatukan sidiknya.
        sidik = sidik_digest(k.level, k.source, k.line_code, k.message)
        if not self._ada_sidik(sidik) and self._jumlah_kelompok() >= BATAS_KELOMPOK_MENUNGGU:
            sidik = SIDIK_LAIN
            k = KelompokGalat(k.level, "autograde", None, PESAN_LAIN, k.pertama_at, k.terakhir_at, k.jumlah)
        message = _potong(k.message)
        source = _potong(k.source)
        self._db.execute(
            "INSERT INTO galat_menunggu (sidik, level, source, line_code, message, pertama_at,"
            " terakhir_at, jumlah, masuk_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(sidik) DO UPDATE SET jumlah = jumlah + excluded.jumlah,"
            " pertama_at = MIN(pertama_at, excluded.pertama_at),"
            " terakhir_at = MAX(terakhir_at, excluded.terakhir_at)",
            (sidik, k.level, source, k.line_code, message, k.pertama_at, k.terakhir_at, k.jumlah, now),
        )

    def _ada_sidik(self, sidik: str) -> bool:
        return self._db.execute("SELECT 1 FROM galat_menunggu WHERE sidik = ?", (sidik,)).fetchone() is not None

    def _jumlah_kelompok(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM galat_menunggu").fetchone()[0]

    def tertua_masuk_at(self) -> float | None:
        with self._lock:
            return self._db.execute("SELECT MIN(masuk_at) FROM galat_menunggu").fetchone()[0]

    # ── tahap 2: kiriman ─────────────────────────────────────────────────

    def susun(self, susun_pesan: Callable[[list[KelompokGalat]], list[str]], *, now: float) -> int:
        """Pindahkan SEMUA galat menunggu jadi pesan siap kirim, satu transaksi.

        `susun_pesan` yang melempar (atau mengembalikan `[]` padahal ada galat
        menunggu, M4) membatalkan semuanya: galat tetap menunggu. Mengembalikan
        jumlah pesan yang dibuat.

        ⚠️ `susun_pesan` TIDAK BOLEH mencatat log lewat handler yang disambungkan ke
        store ini (lihat docstring modul, I2): lock yang dipegang method ini bukan
        reentrant.
        """
        with self._lock:
            self._pemegang_lock = threading.get_ident()
            try:
                # M1: `BEGIN IMMEDIATE` mengunci TULIS sebelum SELECT, bukan sesudah
                # baris pertama ditulis (deferred, bawaan). Tanpa ini koneksi/proses
                # lain bisa menulis galat baru PERSIS di antara SELECT dan DELETE di
                # bawah, lalu galat itu ikut ter-DELETE tanpa pernah masuk kelompok
                # yang dikirim: bukan hilang dari disk (masih ada sampai commit ini),
                # tapi hilang dari HASIL susun ini secara senyap.
                self._db.execute("BEGIN IMMEDIATE")
                try:
                    rows = self._db.execute(
                        "SELECT level, source, line_code, message, pertama_at, terakhir_at, jumlah"
                        " FROM galat_menunggu"
                    ).fetchall()
                    if not rows:
                        self._db.execute("COMMIT")
                        return 0
                    pesan = susun_pesan([KelompokGalat(*r) for r in rows])
                    if not pesan:
                        # M4: rows tidak kosong tapi pemanggil tidak menyusun satu
                        # pesan pun adalah bug pemanggil, bukan "tidak ada yang
                        # dikirim". Membiarkannya lewat berarti DELETE di bawah
                        # membuang galat yang belum pernah benar-benar disusun.
                        raise ValueError(
                            "susun_pesan mengembalikan pesan kosong padahal ada"
                            f" {len(rows)} jenis galat menunggu"
                        )
                    self._db.executemany(
                        "INSERT INTO kiriman (isi, dibuat_at) VALUES (?, ?)", [(p, now) for p in pesan]
                    )
                    self._db.execute("DELETE FROM galat_menunggu")
                    self._set("ringkasan_terakhir_at", now)
                    self._db.execute("COMMIT")
                    return len(pesan)
                except BaseException:
                    # `rollback()`, bukan `execute("ROLLBACK")`: SQLITE_FULL/IOERR bisa
                    # membuat SQLite membatalkan transaksinya sendiri, dan ROLLBACK mentah
                    # sesudahnya melempar "no transaction is active" yang menutupi galat
                    # aslinya. `rollback()` tidak berbuat apa-apa kalau transaksinya sudah
                    # tidak ada.
                    self._db.rollback()
                    raise
            finally:
                self._pemegang_lock = None

    def ada_kiriman(self) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM kiriman LIMIT 1").fetchone() is not None

    def kiriman_berikut(self) -> Kiriman | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, isi, percobaan FROM kiriman ORDER BY id LIMIT 1"
            ).fetchone()
        return Kiriman(row["id"], row["isi"], row["percobaan"]) if row else None

    def tandai_terkirim(self, kiriman_id: int, *, now: float) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM kiriman WHERE id = ?", (kiriman_id,))
            self._set("terkirim_terakhir_at", now)
            self._db.execute(
                "DELETE FROM keadaan WHERE kunci IN ('galat', 'galat_at', 'status_http')"
            )

    def tandai_gagal(
        self, kiriman_id: int, *, galat: str, status_http: int | None, now: float
    ) -> None:
        galat = galat[:_GALAT_CHARS]
        with self._lock, self._db:
            self._db.execute(
                "UPDATE kiriman SET percobaan = percobaan + 1, galat = ?, galat_at = ? WHERE id = ?",
                (galat, now, kiriman_id),
            )
            self._set("galat", galat)
            self._set("galat_at", now)
            if status_http is None:
                self._db.execute("DELETE FROM keadaan WHERE kunci = 'status_http'")
            else:
                self._set("status_http", status_http)

    def ringkasan_terakhir_at(self) -> float | None:
        with self._lock:
            nilai = self._get("ringkasan_terakhir_at")
        return float(nilai) if nilai is not None else None

    def ringkasan(self) -> dict[str, Any]:
        """Untuk layar support: berapa yang menunggu, kapan terakhir, galat terakhir."""
        with self._lock:
            menunggu = self._db.execute(
                "SELECT COUNT(*), COALESCE(SUM(jumlah), 0) FROM galat_menunggu"
            ).fetchone()
            kiriman = self._db.execute("SELECT COUNT(*) FROM kiriman").fetchone()[0]
            keadaan = {r["kunci"]: r["nilai"] for r in self._db.execute("SELECT kunci, nilai FROM keadaan")}
        return {
            "menunggu_jenis": menunggu[0],
            "menunggu_kejadian": menunggu[1],
            "kiriman": kiriman,
            "ringkasan_terakhir_at": _float(keadaan.get("ringkasan_terakhir_at")),
            "terkirim_terakhir_at": _float(keadaan.get("terkirim_terakhir_at")),
            "galat": keadaan.get("galat"),
            "galat_at": _float(keadaan.get("galat_at")),
            "status_http": int(keadaan["status_http"]) if "status_http" in keadaan else None,
        }

    def _get(self, kunci: str) -> str | None:
        row = self._db.execute("SELECT nilai FROM keadaan WHERE kunci = ?", (kunci,)).fetchone()
        return row["nilai"] if row else None

    def _set(self, kunci: str, nilai: object) -> None:
        self._db.execute(
            "INSERT INTO keadaan (kunci, nilai) VALUES (?, ?)"
            " ON CONFLICT(kunci) DO UPDATE SET nilai = excluded.nilai",
            (kunci, str(nilai)),
        )


def _float(nilai: str | None) -> float | None:
    return float(nilai) if nilai is not None else None


def _potong(teks: str) -> str:
    """M3: batasi ukuran teks yang DISIMPAN (bukan yang dipakai `sidik_digest`, itu
    dipanggil dengan teks penuh SEBELUM fungsi ini)."""
    return teks if len(teks) <= _MASUK_CHARS else teks[:_MASUK_CHARS]
