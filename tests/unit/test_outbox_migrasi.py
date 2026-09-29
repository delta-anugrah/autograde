"""Berkas antrean dari versi sebelum batch 2.4: dirapikan di tempat saat dibuka.

Yang dijaga (keputusan 2026-09-28, data tidak boleh hilang): baris yang dulu
berhenti dicoba (`failed`, 50 percobaan) dikirim lagi, tanpa baris ganda, tanpa
kehilangan riwayat percobaannya, dan berkas yang dibuka berkali-kali (restart,
rollback lalu upgrade lagi) tidak berubah sesudah pembukaan pertama.
"""
from __future__ import annotations

import json
import logging
import time

from antrean_line_rakit import berkas_outbox_versi_lama

from palmgrade.integrations.outbox import outbox_store
from palmgrade.integrations.outbox.outbox_store import OutboxStore

TS = "2026-09-20T03:00:00+00:00"
#: TS dalam epoch detik.
EPOCH_TS = 1789873200.0


def _payload(eid: str) -> str:
    return json.dumps({"event_id": eid, "timestamp": TS})


def test_baris_yang_dulu_menyerah_dikirim_lagi(tmp_path):
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [("e1", "failed", 50, _payload("e1")), ("e2", "pending", 3, _payload("e2"))])

    store = OutboxStore(jalur)

    assert store.failed_count() == 0
    assert store.pending_count() == 2
    assert sorted(r["event_id"] for r in store.get_pending()) == ["e1", "e2"]


def test_riwayat_percobaan_tetap_dan_janjang_baru_didahulukan(tmp_path):
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [("lama", "failed", 50, _payload("lama"))])

    store = OutboxStore(jalur)
    store.add_event("baru", "m-1", {"event_id": "baru", "timestamp": TS})

    baris = store._db.execute("SELECT retry_count, last_error FROM outbox_events WHERE event_id = 'lama'").fetchone()
    assert (baris["retry_count"], baris["last_error"]) == (50, "HTTP 503: api mati")
    assert [r["event_id"] for r in store.get_pending()] == ["baru", "lama"]


def test_umur_diisi_dari_timestamp_payload(tmp_path):
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [("e1", "failed", 50, _payload("e1"))])

    isi = OutboxStore(jalur).ringkasan()
    assert (isi["menunggu"], isi["tertua_at"]) == (1, EPOCH_TS)


def test_kolom_ditolak_ditambah_di_tempat_dan_baris_lama_belum_terhitung_ditolak(tmp_path):
    """Kolom baru untuk layar (final review konsol I1), ditambah di tempat seperti
    `dibuat_at`. Baris lama belum terhitung ditolak sampai konsol menjawabnya di
    versi ini: `last_error` versi lama bisa berasal dari api yang sudah mati."""
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [("e1", "failed", 50, _payload("e1"))])

    store = OutboxStore(jalur)

    kolom = {r["name"] for r in store._db.execute("PRAGMA table_info(outbox_events)")}
    assert "ditolak_at" in kolom
    assert store.ringkasan()["ditolak"] == 0


def test_payload_tanpa_timestamp_diisi_jam_buka(tmp_path):
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [("e1", "pending", 0, "{}")])
    sebelum = time.time()

    tertua = OutboxStore(jalur).ringkasan()["tertua_at"]

    assert sebelum <= tertua <= time.time()


def test_membuka_berkali_kali_tidak_mengubah_apa_pun(tmp_path):
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [("e1", "failed", 50, _payload("e1"))])
    pertama = OutboxStore(jalur)
    isi = [tuple(r) for r in pertama._db.execute("SELECT * FROM outbox_events ORDER BY id")]
    pertama._db.close()

    kedua = OutboxStore(jalur)

    assert [tuple(r) for r in kedua._db.execute("SELECT * FROM outbox_events ORDER BY id")] == isi


def test_rollback_lalu_upgrade_lagi_menghidupkan_yang_ditandai_versi_lama(tmp_path):
    """Review focus 4: `autograde use <lama>` menulis `failed` lagi sesudah 50
    percobaan; pembukaan berikutnya oleh versi ini menghidupkannya lagi."""
    jalur = tmp_path / "outbox.db"
    baru = OutboxStore(jalur)
    baru.add_event("e1", "m-1", {"event_id": "e1", "timestamp": TS})
    with baru._db:  # yang dilakukan versi lama pada percobaan ke-50
        baru._db.execute(
            "UPDATE outbox_events SET status = 'failed', retry_count = 50, next_retry_at = ?",
            (time.time() + 600,),
        )
    baru._db.close()

    lagi = OutboxStore(jalur)

    assert lagi.failed_count() == 0
    assert [r["event_id"] for r in lagi.get_pending()] == ["e1"]


def test_serap_berkas_lama_menghidupkan_yang_menyerah(tmp_path):
    """Lampung naik dari versi sebelum batch 1: antrean di `artifacts/` diserap ke
    `state/` DAN yang menyerah dihidupkan, pada boot yang sama."""
    lama = tmp_path / "artifacts" / "outbox.db"
    berkas_outbox_versi_lama(lama, [("e1", "failed", 50, _payload("e1")), ("e2", "pending", 1, _payload("e2"))])
    baru = OutboxStore(tmp_path / "state" / "outbox.db")

    assert baru.serap(lama) == 2
    assert baru.failed_count() == 0
    assert baru.pending_count() == 2
    assert baru.ringkasan()["tertua_at"] == EPOCH_TS


def _lacak_sql(monkeypatch) -> list[str]:
    """Setiap pernyataan SQL yang dijalankan koneksi `OutboxStore` berikutnya."""
    jejak: list[str] = []
    asli = outbox_store.sqlite3.connect

    def connect(*a, **k):
        db = asli(*a, **k)
        db.set_trace_callback(jejak.append)
        return db

    monkeypatch.setattr(outbox_store.sqlite3, "connect", connect)
    return jejak


def test_antrean_besar_dirapikan_per_potongan(tmp_path, monkeypatch):
    """Dibaca per potongan, sungguh: 50 baris dengan potongan 7 = 8 potongan berisi
    ditambah satu yang kosong, bukan satu SELECT yang membaca semuanya."""
    monkeypatch.setattr(outbox_store, "_POTONGAN_RAPIKAN", 7)
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [(f"e{i}", "failed", 50, _payload(f"e{i}")) for i in range(50)])
    jejak = _lacak_sql(monkeypatch)

    store = OutboxStore(jalur)

    potongan = [q for q in jejak if q.lstrip().upper().startswith("SELECT") and "dibuat_at IS NULL" in q]
    assert len(potongan) == 9
    kosong = store._db.execute("SELECT COUNT(*) FROM outbox_events WHERE dibuat_at IS NULL").fetchone()[0]
    assert kosong == 0
    assert store.pending_count() == 50


def test_potongan_dilanjutkan_lewat_kunci_utama_bukan_memindai_ulang(tmp_path):
    """Parkiran Task 2: `WHERE dibuat_at IS NULL LIMIT n` diulang dari awal tiap potongan
    memindai seluruh tabel tiap kali (kuadratik pada antrean besar). Tiap potongan
    melanjutkan dari `id` terakhir, jadi SQLite mencari lewat kunci utama."""
    store = OutboxStore(tmp_path / "outbox.db")

    rencana = " ".join(
        r[3] for r in store._db.execute(f"EXPLAIN QUERY PLAN {outbox_store._SQL_POTONGAN_RAPIKAN}", (0, 7))
    )

    assert "INTEGER PRIMARY KEY" in rencana, rencana


def test_jumlah_yang_dihidupkan_dicatat_sekali(tmp_path, caplog):
    jalur = tmp_path / "outbox.db"
    berkas_outbox_versi_lama(jalur, [("e1", "failed", 50, _payload("e1")), ("e2", "failed", 50, _payload("e2"))])

    with caplog.at_level(logging.WARNING, logger=outbox_store.__name__):
        OutboxStore(jalur)._db.close()
        OutboxStore(jalur)

    catatan = [r.getMessage() for r in caplog.records if "dihidupkan" in r.getMessage()]
    assert len(catatan) == 1
    assert catatan[0].startswith("2 janjang")
