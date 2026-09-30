"""WARNING/ERROR satu line di disk line sendiri, supaya selamat dari `--force-recreate`.

`autograde` start/restart/pull membuat container line ulang, dan `docker logs` ikut
hilang: support yang datang sesudah restart dulu tidak punya apa-apa. Berkas ini hidup
di folder DB line (`state/`, lihat `services/pindah_db_line.py`) dan ditarik konsol ke
tab Log lewat `GET /internal/log` (batch 3.2, kontrak di `domain/log_line.py`).

Kebiasaan sama dengan store lain: WAL, `synchronous=FULL`, satu kunci. Yang menulis
cuma thread penulis `AntreanLogLine`, tidak pernah thread deteksi (aturan 1b).
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..domain.log_line import (
    BATAS_BARIS_LINE,
    EntriLog,
    mulai_dari,
    potong_detail,
    potong_pesan,
)
from ..domain.sidik_log import normalkan_pesan

#: Nama berkas di folder DB line. Digolongkan `SELAMAT_DI_STATE` (hapus_data_line):
#: berkasnya sudah terbuka sejak proses mulai, jadi hapus-saat-boot tidak boleh menyentuhnya.
NAMA_DB_LOG_LINE = "log_line.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS log_line (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    seq       INTEGER NOT NULL,
    first_at  REAL NOT NULL,
    last_at   REAL NOT NULL,
    level     TEXT NOT NULL,
    source    TEXT NOT NULL,
    message   TEXT NOT NULL,
    detail    TEXT,
    sidik     TEXT NOT NULL,
    count     INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_log_line_seq ON log_line (seq);
CREATE INDEX IF NOT EXISTS idx_log_line_sidik ON log_line (sidik, last_at DESC);
CREATE TABLE IF NOT EXISTS log_line_meta (
    kunci TEXT PRIMARY KEY,
    nilai TEXT NOT NULL
);
"""

#: Sama dengan `LogStore.MERGE_WINDOW_S` konsol: pesan identik dalam 60 detik digabung.
JENDELA_GABUNG_S = 60.0


class LogLineStore:
    def __init__(self, db_path: Path, *, batas_baris: int = BATAS_BARIS_LINE) -> None:
        self._batas = batas_baris
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)
            # Sekali per berkas: berkas baru (reset data) = generasi baru.
            self._db.execute(
                "INSERT OR IGNORE INTO log_line_meta (kunci, nilai) VALUES ('generasi', ?)",
                (uuid.uuid4().hex,),
            )
            self._generasi = self._meta("generasi")

    @property
    def generasi(self) -> str:
        return self._generasi

    def write(
        self, level: str, source: str, message: str, detail: str | None, *, now: float
    ) -> None:
        """Satu kejadian (bentuk `_LogSink` milik `core/log_sink.py`)."""
        self.tulis_banyak([EntriLog(level, source, message, detail, now)])

    def tulis_banyak(self, entri: Iterable[EntriLog], *, dibuang_antrean: int = 0) -> None:
        """Satu transaksi untuk satu kurasan antrean penulis.

        `dibuang_antrean` = kejadian yang sudah dibuang antrean di memori karena
        penuh; dijumlahkan ke `dibuang` supaya konsol bisa menyebutnya.
        """
        with self._lock, self._db:
            dibuang = dibuang_antrean
            for e in entri:
                dibuang += self._tulis_satu(e)
            if dibuang:
                self._tambah_meta("dibuang", dibuang)

    def _tulis_satu(self, e: EntriLog) -> int:
        """Tulis atau gabung satu kejadian. Mengembalikan jumlah baris yang dibuang batas."""
        message = potong_pesan(e.message)
        sidik = _sidik(e.level, e.source, message)
        seq = self._tambah_meta("seq", 1)
        row = self._db.execute(
            "SELECT id FROM log_line WHERE sidik = ? AND last_at >= ?"
            " ORDER BY last_at DESC LIMIT 1",
            (sidik, e.at - JENDELA_GABUNG_S),
        ).fetchone()
        if row is not None:
            self._db.execute(
                "UPDATE log_line SET count = count + 1, last_at = MAX(last_at, ?), seq = ?,"
                " detail = COALESCE(detail, ?) WHERE id = ?",
                (e.at, seq, potong_detail(e.detail), row["id"]),
            )
            return 0
        self._db.execute(
            "INSERT INTO log_line (seq, first_at, last_at, level, source, message, detail, sidik)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, e.at, e.at, e.level, e.source, message, potong_detail(e.detail), sidik),
        )
        return self._db.execute(
            "DELETE FROM log_line WHERE seq <= ("
            " SELECT seq FROM log_line ORDER BY seq DESC LIMIT 1 OFFSET ?)",
            (self._batas,),
        ).rowcount

    def ambil(self, *, setelah: int, generasi: str, batas: int) -> dict[str, Any]:
        """Satu halaman untuk `GET /internal/log`, urut `seq` naik."""
        with self._lock:
            mulai = mulai_dari(setelah, generasi, self._generasi)
            rows = self._db.execute(
                "SELECT id, seq, first_at, last_at, level, source, message, detail, count"
                " FROM log_line WHERE seq > ? ORDER BY seq LIMIT ?",
                (mulai, batas + 1),
            ).fetchall()
            dibuang = int(self._meta("dibuang") or 0)
        lagi = len(rows) > batas
        rows = rows[:batas]
        return {
            "generasi": self._generasi,
            "entri": [dict(r) for r in rows],
            "seq_akhir": rows[-1]["seq"] if rows else mulai,
            "lagi": lagi,
            "dibuang": dibuang,
        }

    def _meta(self, kunci: str) -> str | None:
        row = self._db.execute(
            "SELECT nilai FROM log_line_meta WHERE kunci = ?", (kunci,)
        ).fetchone()
        return row["nilai"] if row else None

    def _tambah_meta(self, kunci: str, n: int) -> int:
        """Penghitung di tabel meta, di dalam transaksi pemanggil. Mengembalikan nilai baru."""
        baru = int(self._meta(kunci) or 0) + n
        self._db.execute(
            "INSERT INTO log_line_meta (kunci, nilai) VALUES (?, ?)"
            " ON CONFLICT(kunci) DO UPDATE SET nilai = excluded.nilai",
            (kunci, str(baru)),
        )
        return baru


def _sidik(level: str, source: str, message: str) -> str:
    return hashlib.sha256(f"{level}|{source}|{normalkan_pesan(message)}".encode()).hexdigest()[:32]
