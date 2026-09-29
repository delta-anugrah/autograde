"""`OutboxStore.serap`: antrean lama di artifacts/ diserap ke berkas baru di state/.

Yang dijaga: tidak ada baris hilang (termasuk yang cuma ada di berkas WAL saat
proses lama mati), tidak ada baris ganda (mengulang aman), dan baris yang
sudah ada di berkas baru tidak disentuh.
"""
from __future__ import annotations

import shutil
import sqlite3

import pytest

from palmgrade.integrations.outbox import outbox_store
from palmgrade.integrations.outbox.outbox_store import OutboxStore


def _lama(tmp_path, *event_ids):
    lama = OutboxStore(tmp_path / "lama" / "outbox.db")
    for eid in event_ids:
        lama.add_event(eid, "m-1", {"event_id": eid})
    return lama


def test_baris_lama_pindah_utuh_yang_menyerah_dihidupkan(tmp_path):
    lama = _lama(tmp_path, "e1", "e2")
    with lama._db:  # yang ditulis versi sebelum batch 2.4 pada percobaan ke-50
        lama._db.execute("UPDATE outbox_events SET status = 'failed' WHERE event_id = 'e2'")
    lama._db.close()
    baru = OutboxStore(tmp_path / "state" / "outbox.db")

    assert baru.serap(tmp_path / "lama" / "outbox.db") == 2
    assert baru.pending_count() == 2
    assert baru.failed_count() == 0


def test_serap_dua_kali_tidak_menggandakan(tmp_path):
    _lama(tmp_path, "e1")._db.close()
    baru = OutboxStore(tmp_path / "state" / "outbox.db")
    baru.serap(tmp_path / "lama" / "outbox.db")

    assert baru.serap(tmp_path / "lama" / "outbox.db") == 0
    assert baru.pending_count() == 1


def test_baris_yang_sudah_ada_di_berkas_baru_tetap(tmp_path):
    _lama(tmp_path, "e1", "e2")._db.close()
    baru = OutboxStore(tmp_path / "state" / "outbox.db")
    baru.add_event("e3", "m-1", {"event_id": "e3"})

    baru.serap(tmp_path / "lama" / "outbox.db")

    assert sorted(r["event_id"] for r in baru.get_pending(limit=10)) == ["e1", "e2", "e3"]


def test_berkas_bukan_outbox_melempar(tmp_path):
    rusak = tmp_path / "outbox.db"
    rusak.write_bytes(b"bukan sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        OutboxStore(tmp_path / "state" / "outbox.db").serap(rusak)


def test_baris_yang_cuma_ada_di_wal_ikut_terserap(tmp_path):
    """Listrik mati: `outbox.db` utama belum memuat baris yang sudah commit,
    barisnya masih di `outbox.db-wal`. Salinan tiga berkas pada saat itu harus
    tetap menyerahkan semuanya, bukan cuma isi berkas utama."""
    hidup = tmp_path / "hidup"
    lama = OutboxStore(hidup / "outbox.db")
    lama._db.execute("PRAGMA wal_autocheckpoint=0")
    for eid in ("w1", "w2", "w3"):
        lama.add_event(eid, "m-1", {"event_id": eid})
    mati = tmp_path / "mati"
    mati.mkdir()
    for nama in ("outbox.db", "outbox.db-wal", "outbox.db-shm"):
        shutil.copy2(hidup / nama, mati / nama)
    lama._db.close()
    assert _baris_di_berkas_utama_saja(mati / "outbox.db") == 0

    baru = OutboxStore(tmp_path / "state" / "outbox.db")

    assert baru.serap(mati / "outbox.db") == 3
    assert sorted(r["event_id"] for r in baru.get_pending(limit=10)) == ["w1", "w2", "w3"]


def test_antrean_besar_diserap_per_potongan(tmp_path, monkeypatch):
    """Antrean lama bisa berbulan-bulan (line tanpa konsol). Dibaca per potongan,
    bukan `fetchall()` sekaligus: `MemoryError` di sini membuat berkas lama
    tertinggal tanpa pernah terkirim."""
    monkeypatch.setattr(outbox_store, "_POTONGAN_SERAP", 2)
    _lama(tmp_path, "e1", "e2", "e3", "e4", "e5")._db.close()
    baru = OutboxStore(tmp_path / "state" / "outbox.db")
    baru.add_event("e3", "m-1", {"event_id": "e3"})

    assert baru.serap(tmp_path / "lama" / "outbox.db") == 4
    assert sorted(r["event_id"] for r in baru.get_pending(limit=10)) == ["e1", "e2", "e3", "e4", "e5"]


class _GagalDiPotonganKedua:
    """Koneksi tujuan yang gagal menulis potongan kedua (disk penuh)."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db
        self.tulis = 0

    def __getattr__(self, nama):
        return getattr(self._db, nama)

    def __enter__(self):
        return self._db.__enter__()

    def __exit__(self, *exc):
        return self._db.__exit__(*exc)

    def executemany(self, sql, baris):
        self.tulis += 1
        if self.tulis == 2:
            raise sqlite3.OperationalError("database or disk is full")
        return self._db.executemany(sql, baris)


def test_gagal_di_tengah_tidak_ada_potongan_yang_tercommit(tmp_path, monkeypatch):
    """Satu commit untuk seluruh antrean: potongan pertama tidak boleh tersimpan
    sendirian lalu berkas lama dihapus seolah semuanya sudah pindah."""
    monkeypatch.setattr(outbox_store, "_POTONGAN_SERAP", 2)
    _lama(tmp_path, "e1", "e2", "e3", "e4")._db.close()
    baru = OutboxStore(tmp_path / "state" / "outbox.db")
    asli = baru._db
    baru._db = _GagalDiPotonganKedua(asli)

    with pytest.raises(sqlite3.OperationalError):
        baru.serap(tmp_path / "lama" / "outbox.db")

    baru._db = asli
    assert baru.pending_count() == 0


def _baris_di_berkas_utama_saja(db) -> int:
    """Isi berkas utama tanpa WAL-nya (`immutable=1` tidak membaca `-wal`)."""
    utama = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    try:
        return utama.execute("SELECT COUNT(*) FROM outbox_events").fetchone()[0]
    except sqlite3.OperationalError:
        return 0  # tabelnya sendiri pun masih di WAL
    finally:
        utama.close()
