"""Antrean janjang line ke konsol (`BACKEND_URL`), di SQLite milik line.

Batch 2.4 (2026-09-28): TANPA batas nyerah. Baris hanya keluar dari sini saat
konsol mengonfirmasi (`mark_delivered` menghapusnya); tidak ada lagi status
`failed` yang berhenti dicoba. Baris `failed` tulisan versi lama dihidupkan
lagi saat berkas dibuka dan saat antrean lama diserap (`_rapikan_baris_lama`).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ...domain.kirim_antrean_line import (
    JEDA_BARIS_DASAR_S,
    JEDA_BARIS_MAKS_S,
    jeda_mundur,
    waktu_janjang,
)

logger = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS outbox_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL UNIQUE,
    machine_id  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at REAL NOT NULL DEFAULT 0,
    last_error  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    dibuat_at   REAL,
    ditolak_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_outbox_status_retry
    ON outbox_events (status, next_retry_at);
"""

#: Baris antrean lama yang dibaca per potongan saat diserap. Antrean line yang
#: berbulan-bulan tanpa konsol bisa besar; `fetchall()` sekaligus bisa
#: `MemoryError`, dan itu meninggalkan berkas lama yang tidak pernah terkirim.
_POTONGAN_SERAP = 1000
#: Alasan yang sama untuk mengisi `dibuat_at` baris dari versi sebelum batch 2.4.
_POTONGAN_RAPIKAN = 1000


class OutboxStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_db()
        self._rapikan_baris_lama()

    def _init_db(self) -> None:
        with self._lock, self._db:
            # Durability eksplisit (jangan andalkan default implementasi):
            # - WAL: lebih tahan korupsi saat power-loss + baca/tulis tidak saling blok.
            # - synchronous=FULL: fsync tiap commit → transaksi yang sudah commit
            #   selamat dari mati listrik. Outbox write rate rendah, biaya fsync ringan.
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_CREATE_SQL)
            kolom = {baris["name"] for baris in self._db.execute("PRAGMA table_info(outbox_events)")}
            # Ditambah di tempat, bukan tabel baru: image lama menyebut kolomnya satu
            # per satu di INSERT/UPDATE, jadi rollback tetap membaca berkas ini.
            for nama in ("dibuat_at", "ditolak_at"):
                if nama not in kolom:
                    self._db.execute(f"ALTER TABLE outbox_events ADD COLUMN {nama} REAL")

    def _rapikan_baris_lama(self) -> int:
        """Perbaiki di tempat dua hal tulisan versi sebelum batch 2.4. Idempoten.

        - `status` selain `pending` (dulu `failed` sesudah 50 percobaan) kembali
          `pending` dan jatuh tempo sekarang. Hitungan percobaan dan `last_error`
          tetap: janjang baru (percobaan 0) tetap didahulukan `get_pending`, dan
          support masih bisa membaca kenapa baris itu dulu gagal.
        - `dibuat_at` kosong diisi dari `timestamp` payload, per potongan.

        Satu transaksi: mati listrik di tengah = tidak ada yang berubah, dan
        pembukaan berikutnya mengulang dari awal.
        """
        with self._lock, self._db:
            dihidupkan = self._db.execute(
                "UPDATE outbox_events SET status='pending', next_retry_at=0 WHERE status <> 'pending'"
            ).rowcount
            cadangan = time.time()
            while potongan := self._db.execute(
                "SELECT id, payload FROM outbox_events WHERE dibuat_at IS NULL LIMIT ?",
                (_POTONGAN_RAPIKAN,),
            ).fetchall():
                self._db.executemany(
                    "UPDATE outbox_events SET dibuat_at=? WHERE id=?",
                    [(waktu_janjang(baris["payload"], cadangan), baris["id"]) for baris in potongan],
                )
        if dihidupkan:
            logger.warning(
                "%d janjang yang dulu berhenti dicoba (batas 50 percobaan versi lama) "
                "dihidupkan lagi dan akan dikirim ke konsol",
                dihidupkan,
            )
        return dihidupkan

    def add_event(self, event_id: str, machine_id: str, payload: dict[str, Any]) -> None:
        """`dibuat_at` = kapan janjang itu digrading, dari `timestamp` payload (jam
        tulis kalau tidak ada): satu arti yang sama dengan baris dari versi lama."""
        teks = json.dumps(payload)
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO outbox_events (event_id, machine_id, payload, dibuat_at) "
                "VALUES (?, ?, ?, ?)",
                (event_id, machine_id, teks, waktu_janjang(teks, time.time())),
            )

    def get_pending(self, limit: int = 20) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            rows = self._db.execute(
                """SELECT id, event_id, payload, retry_count
                   FROM outbox_events
                   WHERE status = 'pending' AND next_retry_at <= ?
                   ORDER BY retry_count ASC, id ASC LIMIT ?""",
                (now, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def berikutnya(self) -> dict[str, Any] | None:
        """Satu baris untuk menguji sambungan saat konsol putus, jadwal mundurnya diabaikan.

        Urutan sama dengan `get_pending`: yang paling jarang dicoba lebih dulu, jadi
        percobaan berturut-turut berpindah baris dan satu baris beracun tidak
        menjadi satu-satunya penguji.
        """
        with self._lock:
            baris = self._db.execute(
                """SELECT id, event_id, payload, retry_count FROM outbox_events
                   ORDER BY retry_count ASC, id ASC LIMIT 1"""
            ).fetchone()
        return dict(baris) if baris else None

    def mark_delivered(self, row_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM outbox_events WHERE id = ?", (row_id,))

    def mark_failed_attempt(self, row_id: int, error: str, *, ditolak: bool = False) -> None:
        """Catat satu percobaan gagal dan jadwal berikutnya. Baris TIDAK pernah menyerah.

        `ditolak` = konsol menjawab dan menolak BARIS ini (400, 422): `ditolak_at`
        distempel sekarang. Gagal jenis lain mengosongkannya, karena yang dihitung
        layar adalah penolakan TERAKHIR baris itu, bukan penolakan kapan pun.
        """
        with self._lock, self._db:
            row = self._db.execute("SELECT retry_count FROM outbox_events WHERE id = ?", (row_id,)).fetchone()
            if not row:
                return
            retry = row["retry_count"] + 1
            sekarang = time.time()
            next_retry = sekarang + jeda_mundur(retry, dasar=JEDA_BARIS_DASAR_S, maks=JEDA_BARIS_MAKS_S)
            self._db.execute(
                "UPDATE outbox_events SET retry_count=?, next_retry_at=?, last_error=?, status='pending', "
                "ditolak_at=? WHERE id=?",
                (retry, next_retry, error[:500], sekarang if ditolak else None, row_id),
            )

    def pending_count(self) -> int:
        """Janjang yang BELUM sampai ke konsol, apa pun statusnya.

        Baris terkirim dihapus, jadi setiap baris di tabel belum sampai. Host
        `autograde reset-data` dan Danger Zone percaya angka ini sebelum menghapus.
        """
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) AS n FROM outbox_events").fetchone()
        return row["n"] if row else 0

    def failed_count(self) -> int:
        """Baris berstatus `failed`. Selalu 0 sejak batch 2.4 (dihidupkan saat berkas
        dibuka); tetap dilapor di `/health/detail` sebagai `outbox_failed` supaya
        bentuk jawaban tidak berubah."""
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) as n FROM outbox_events WHERE status='failed'").fetchone()
        return row["n"] if row else 0

    def kirim_ulang_sekarang(self) -> int:
        """Semua baris yang belum terkirim jatuh tempo SEKARANG. Mengembalikan jumlahnya.

        Dipakai saat konsol tersambung lagi (otomatis) dan tombol Kirim Ulang
        (manual). Hitungan percobaan dan `last_error` tidak disentuh: urutan
        `get_pending` tetap mendahulukan janjang baru, dan alasan gagal terakhir
        tetap terbaca sampai percobaan berikutnya menimpanya.
        """
        with self._lock, self._db:
            self._db.execute(
                "UPDATE outbox_events SET status='pending', next_retry_at=0 "
                "WHERE next_retry_at <> 0 OR status <> 'pending'"
            )
            return self._db.execute("SELECT COUNT(*) AS n FROM outbox_events").fetchone()["n"]

    def ringkasan(self) -> dict[str, Any]:
        """Untuk layar: yang menunggu, kapan janjang tertuanya digrading (epoch detik),
        dan berapa yang percobaan terakhirnya DITOLAK konsol, dengan jam dan alasan
        penolakan terbaru. Baris ditolak ikut `menunggu`: tidak ada yang dibuang."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n, MIN(dibuat_at) AS tertua, COUNT(ditolak_at) AS ditolak "
                "FROM outbox_events"
            ).fetchone()
            terbaru = self._db.execute(
                "SELECT ditolak_at, last_error FROM outbox_events WHERE ditolak_at IS NOT NULL "
                "ORDER BY ditolak_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return {
            "menunggu": row["n"],
            "tertua_at": row["tertua"],
            "ditolak": row["ditolak"],
            "ditolak_at": terbaru["ditolak_at"] if terbaru else None,
            "ditolak_alasan": terbaru["last_error"] if terbaru else None,
        }

    def serap(self, lama: Path) -> int:
        """Salin antrean dari `outbox.db` lama (di artifacts/, sebelum batch 1) ke berkas ini.

        Idempoten per `event_id` (INSERT OR IGNORE): mengulang aman, dan baris yang
        sudah ada di sini (PC yang sempat rollback) tidak disentuh. Hitungan
        percobaan dan jadwal kirim ulang ikut apa adanya; baris `failed` dan
        `dibuat_at` yang kosong dirapikan sesudahnya (`_rapikan_baris_lama`).

        Sumbernya dibuka sebagai koneksi SQLite biasa, bukan disalin per berkas:
        baris yang sudah commit tapi masih di `-wal` (proses lama mati sebelum
        checkpoint) ikut terbaca, dan journal yang tertinggal dipulihkan dulu.

        Dibaca per potongan (`_POTONGAN_SERAP`), tapi ditulis dalam SATU
        transaksi: gagal di potongan mana pun (disk penuh) tidak meninggalkan
        separuh antrean yang tercommit, dan pemanggil baru menghapus berkas lama
        sesudah fungsi ini kembali, yaitu sesudah commit itu. Merapikan adalah
        transaksi kedua; mati listrik di antaranya dirapikan pembukaan berikutnya.
        """
        sumber = sqlite3.connect(str(lama))
        try:
            baca = sumber.execute(
                "SELECT event_id, machine_id, payload, retry_count, next_retry_at, last_error, status "
                "FROM outbox_events ORDER BY id"
            )
            diserap = 0
            with self._lock, self._db:
                while potongan := baca.fetchmany(_POTONGAN_SERAP):
                    cur = self._db.executemany(
                        "INSERT OR IGNORE INTO outbox_events "
                        "(event_id, machine_id, payload, retry_count, next_retry_at, last_error, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        potongan,
                    )
                    diserap += cur.rowcount
        finally:
            sumber.close()
        self._rapikan_baris_lama()
        return diserap
