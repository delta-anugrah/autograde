"""Unit tests for the durable line outbox store (B1, batch 2.4).

The outbox is the crash-safe delivery guarantee between a camera line and the
console: detection events are persisted here, then OutboxRetryWorker ships
them. Since batch 2.4 there is NO dead letter: a row leaves only when the
console confirms it. Uses a throwaway SQLite DB in tmp_path.
"""
from __future__ import annotations

import time

import pytest

from palmgrade.domain.kirim_antrean_line import JEDA_BARIS_DASAR_S, JEDA_BARIS_MAKS_S
from palmgrade.integrations.outbox.outbox_store import OutboxStore


@pytest.fixture
def store(tmp_path):
    return OutboxStore(db_path=tmp_path / "outbox.db")


def _payload(**over):
    base = {"event_id": "e1", "prediction": "Acc", "ripeness_status": "ACC"}
    base.update(over)
    return base


def _baris(store, row_id):
    return store._db.execute("SELECT * FROM outbox_events WHERE id=?", (row_id,)).fetchone()


def test_add_then_pending_returns_event(store):
    store.add_event("e1", "m1", _payload())
    pending = store.get_pending()

    assert len(pending) == 1
    assert pending[0]["event_id"] == "e1"
    assert store.pending_count() == 1


def test_duplicate_event_id_is_ignored(store):
    # uuid5 makes event_id deterministic: reprocessing the same frame after a
    # crash must NOT create a second outbox row.
    store.add_event("dup", "m1", _payload(event_id="dup"))
    store.add_event("dup", "m1", _payload(event_id="dup"))

    assert store.pending_count() == 1


def test_mark_delivered_removes_row(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    store.mark_delivered(row_id)

    assert store.pending_count() == 0
    assert store.get_pending() == []


def test_failed_attempt_backs_off_and_stays_pending(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    store.mark_failed_attempt(row_id, "HTTP 500")

    # Backed off into the future → not immediately returned by get_pending.
    assert store.get_pending() == []
    # But still waiting (retryable), not delivered.
    assert store.pending_count() == 1


def test_backoff_is_exponential_from_base(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    before = time.time()
    store.mark_failed_attempt(row_id, "err")  # retry 1 → base delay
    row = _baris(store, row_id)
    assert row["retry_count"] == 1
    assert JEDA_BARIS_DASAR_S - 1 <= row["next_retry_at"] - before <= JEDA_BARIS_DASAR_S + 2


def test_backoff_never_exceeds_max(store):
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    for _ in range(60):
        before = time.time()
        store.mark_failed_attempt(row_id, "err")
    assert _baris(store, row_id)["next_retry_at"] - before <= JEDA_BARIS_MAKS_S + 1


def test_tidak_pernah_menyerah_sesudah_ratusan_percobaan(store):
    """Batch 2.4: dulu percobaan ke-50 (±7,3 jam konsol mati) menandai `failed`
    dan baris itu tidak pernah dicoba lagi."""
    store.add_event("e1", "m1", _payload())
    row_id = store.get_pending()[0]["id"]

    for _ in range(300):
        store.mark_failed_attempt(row_id, "HTTP 503")

    baris = _baris(store, row_id)
    assert (baris["retry_count"], baris["status"]) == (300, "pending")
    assert store.pending_count() == 1
    assert store.failed_count() == 0


def test_pending_count_menghitung_semua_yang_belum_terkirim(store):
    """Host `autograde reset-data` dan Danger Zone percaya angka ini sebelum
    menghapus. Baris berstatus apa pun (termasuk `failed` tulisan versi lama
    sesudah rollback) belum sampai ke konsol."""
    store.add_event("e1", "m1", _payload())
    with store._db:
        store._db.execute(
            "INSERT INTO outbox_events (event_id, machine_id, payload, status) VALUES ('e2', 'm1', '{}', 'failed')"
        )

    assert store.pending_count() == 2


def test_dibuat_at_diisi_saat_ditambah(store):
    sebelum = time.time()
    store.add_event("e1", "m1", _payload())

    assert sebelum <= _baris(store, store.get_pending()[0]["id"])["dibuat_at"] <= time.time()


def test_ringkasan_kosong(store):
    assert store.ringkasan() == {"menunggu": 0, "tertua_at": None}


def test_ringkasan_menyebut_jumlah_dan_yang_tertua(store):
    store.add_event("e1", "m1", _payload())
    store.add_event("e2", "m1", _payload(event_id="e2"))
    with store._db:
        store._db.execute("UPDATE outbox_events SET dibuat_at = 1000.0 WHERE event_id = 'e2'")

    assert store.ringkasan() == {"menunggu": 2, "tertua_at": 1000.0}


def test_berikutnya_mengabaikan_jadwal_mundur(store):
    """Percobaan sambungan saat konsol putus: satu baris, walau semuanya sedang mundur."""
    store.add_event("e1", "m1", _payload())
    store.mark_failed_attempt(store.get_pending()[0]["id"], "putus")

    assert store.get_pending() == []
    assert store.berikutnya()["event_id"] == "e1"


def test_berikutnya_kosong(store):
    assert store.berikutnya() is None


def test_berikutnya_mendahulukan_yang_paling_jarang_dicoba(store):
    store.add_event("lama", "m1", _payload(event_id="lama"))
    store.add_event("baru", "m1", _payload(event_id="baru"))
    lama = next(r["id"] for r in store.get_pending() if r["event_id"] == "lama")
    store.mark_failed_attempt(lama, "putus")

    assert store.berikutnya()["event_id"] == "baru"


def test_wal_mode_enabled(store):
    mode = store._db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
