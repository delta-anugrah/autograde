"""Log line masuk `event_log` konsol (batch 3.2): skema tambahan + serapan satu halaman.

Fungsi atas koneksi milik `LogStore` (dipanggil di dalam kunci dan transaksinya), bukan
store kedua: baris log dan kursor harus maju dalam SATU transaksi. Listrik mati di
tengah serapan = tidak ada yang tersimpan dan kursor tidak maju, jadi tarikan
berikutnya meminta halaman yang sama; tersimpan sebagian lalu kursor tertinggal akan
menggandakan baris, kursor maju tanpa barisnya akan menghilangkannya.

Satu baris log line = satu baris `event_log`, dikenali `(line_code, asal)` dengan
`asal = "<generasi>:<id baris di line>"`. Baris yang datang lagi (hitungannya naik di
line) memperbarui barisnya, tidak menambah baris. `fingerprint` baris line berawalan
`line:`, jadi penggabungan pesan milik konsol sendiri (`LogStore.write`, sidik 32 hex)
tidak pernah menyentuh baris line.

ERROR yang baru untuk digest Discord dihitung `galat_baru` SEBELUM serapan, tanpa menulis:
pemanggil meneruskannya ke antrean Discord dulu, baru menyerap. Dua batas hitungan Discord
yang sengaja diterima (paling sedikit sekali, tidak pernah hilang):

- Konsol mati di antara meneruskan dan menyerap: halaman yang sama ditarik lagi sesudah
  start dan hitungannya diteruskan lagi. Serapan yang GAGAL tanpa konsol mati (event_log
  rusak saat jalan, disk penuh) tidak menggandakan: `TarikLogLineWorker` mengingat hitungan
  yang sudah diteruskan tapi belum terserap dan memberikannya lewat `sudah`, jadi tarikan
  ulang cuma meneruskan tambahannya.
- Danger Zone mengosongkan `event_log` (atau retensi membuang baris line) lalu line mengirim
  lagi baris yang sama (hitungannya naik): hitungan tersimpan jadi nol, jadi seluruh
  hitungan baris itu diteruskan lagi, bukan cuma tambahannya.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from ..domain.log_line import EntriTarik, JawabanLog, KursorLine
from ..domain.sidik_log import dengan_jenis_galat

_SKEMA_LINE_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_event_log_asal
    ON event_log (line_code, asal) WHERE asal IS NOT NULL;
CREATE TABLE IF NOT EXISTS log_line_kursor (
    line_code  TEXT PRIMARY KEY,
    generasi   TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    dibuang    INTEGER NOT NULL DEFAULT 0,
    diubah_at  REAL NOT NULL
);
"""
#: Kolom tambahan `event_log`, nullable: baris milik konsol sendiri membiarkannya kosong,
#: dan konsol versi lama (rollback) menulis tanpa menyebutnya.
KOLOM_LINE = ("line_code", "asal")


@dataclass(frozen=True)
class TambahGalat:
    """ERROR line yang belum terlihat konsol, untuk digest Discord (batch 3.5)."""

    level: str
    source: str
    line_code: str
    message: str
    pertama_at: float
    terakhir_at: float
    tambah: int


@dataclass(frozen=True)
class HasilSerap:
    kursor: KursorLine
    #: Baris yang dibuang line sebelum sempat ditarik, sejak serapan sebelumnya.
    dibuang_baru: int


def pasang_skema_line(db: sqlite3.Connection) -> None:
    """Idempoten. Berkas `log_kejadian.db` lama diberi kolom di tempat, isinya utuh."""
    kolom = {r[1] for r in db.execute("PRAGMA table_info(event_log)")}
    for nama in KOLOM_LINE:
        if nama not in kolom:
            db.execute(f"ALTER TABLE event_log ADD COLUMN {nama} TEXT")
    db.executescript(_SKEMA_LINE_SQL)


def kursor_line(db: sqlite3.Connection, line_code: str) -> KursorLine:
    row = db.execute(
        "SELECT generasi, seq, dibuang FROM log_line_kursor WHERE line_code = ?", (line_code,)
    ).fetchone()
    return KursorLine(row[0], row[1], row[2]) if row else KursorLine()


def galat_baru(
    db: sqlite3.Connection, line_code: str, jawaban: JawabanLog, *, sudah: Mapping[int, int] | None = None
) -> tuple[TambahGalat, ...]:
    """ERROR halaman ini yang belum terlihat konsol, TANPA menulis apa pun.

    Pembandingnya hitungan yang sudah tersimpan: baris yang digabung di line sesudah
    ditarik cuma menyumbang tambahannya, halaman yang sudah diserap menyumbang nol.
    `sudah` = id baris line (generasi halaman ini) -> hitungan yang sudah diteruskan
    tapi belum terserap; yang lebih besar dari keduanya yang jadi pembanding.
    """
    sudah = sudah or {}
    galat = []
    for e in jawaban.entri:
        if e.level != "ERROR":
            continue
        dasar = max(_hitungan_tersimpan(db, line_code, jawaban.generasi, e), sudah.get(e.id, 0))
        tambah = e.count - dasar
        if tambah > 0:
            pesan = dengan_jenis_galat(e.message, e.detail)
            galat.append(TambahGalat(e.level, e.source, line_code, pesan, e.first_at, e.last_at, tambah))
    return tuple(galat)


def serap_line(
    db: sqlite3.Connection, line_code: str, jawaban: JawabanLog, *, now: float
) -> HasilSerap:
    """Simpan satu halaman dan majukan kursor. Pemanggil memegang kunci + transaksi."""
    lama = kursor_line(db, line_code)
    dibuang_lama = lama.dibuang if lama.generasi == jawaban.generasi else 0
    for e in jawaban.entri:
        _simpan_entri(db, line_code, jawaban.generasi, e)
    baru = KursorLine(jawaban.generasi, jawaban.seq_akhir, jawaban.dibuang)
    db.execute(
        "INSERT INTO log_line_kursor (line_code, generasi, seq, dibuang, diubah_at)"
        " VALUES (?, ?, ?, ?, ?) ON CONFLICT(line_code) DO UPDATE SET"
        " generasi = excluded.generasi, seq = excluded.seq, dibuang = excluded.dibuang,"
        " diubah_at = excluded.diubah_at",
        (line_code, baru.generasi, baru.seq, baru.dibuang, now),
    )
    return HasilSerap(baru, max(0, jawaban.dibuang - dibuang_lama))


def _asal(generasi: str, e: EntriTarik) -> str:
    return f"{generasi}:{e.id}"


def _hitungan_tersimpan(db: sqlite3.Connection, line_code: str, generasi: str, e: EntriTarik) -> int:
    row = db.execute(
        "SELECT count FROM event_log WHERE line_code = ? AND asal = ?", (line_code, _asal(generasi, e))
    ).fetchone()
    return row[0] if row else 0


def _simpan_entri(db: sqlite3.Connection, line_code: str, generasi: str, e: EntriTarik) -> None:
    """Insert atau perbarui satu baris."""
    asal = _asal(generasi, e)
    row = db.execute(
        "SELECT id FROM event_log WHERE line_code = ? AND asal = ?", (line_code, asal)
    ).fetchone()
    if row is None:
        db.execute(
            "INSERT INTO event_log (logged_at, level, source, message, detail, fingerprint,"
            " count, last_seen_at, line_code, asal) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e.first_at, e.level, e.source, e.message, e.detail,
             f"line:{line_code}:{asal}", e.count, e.last_at, line_code, asal),
        )
        return
    db.execute(
        "UPDATE event_log SET count = ?, last_seen_at = ?, detail = COALESCE(?, detail)"
        " WHERE id = ?",
        (e.count, e.last_at, e.detail, row[0]),
    )
