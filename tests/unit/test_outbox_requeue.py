"""Kirim Ulang di store antrean line (batch 2.4): semua baris jatuh tempo SEKARANG.

Dulu `requeue_failed()` cuma memindahkan baris dead-letter. Sejak batch 2.4 tidak
ada dead-letter; yang dibutuhkan saat konsol pulih (otomatis) atau saat support
menekan Kirim Ulang (manual) adalah antrean yang tidak lagi menunggu jadwal
mundurnya.
"""
from __future__ import annotations

from palmgrade.integrations.outbox.outbox_store import OutboxStore


def _store_mundur(tmp_path, *event_ids):
    store = OutboxStore(db_path=tmp_path / "outbox.db")
    for eid in event_ids:
        store.add_event(eid, "m1", {"event_id": eid})
    for row in store.get_pending(limit=100):
        for _ in range(4):
            store.mark_failed_attempt(row["id"], "HTTP 503: konsol sibuk")
    assert store.get_pending() == []
    return store


def test_kosong_tidak_mengubah_apa_pun(tmp_path):
    assert OutboxStore(db_path=tmp_path / "outbox.db").kirim_ulang_sekarang() == 0


def test_semua_baris_jatuh_tempo_sekarang(tmp_path):
    store = _store_mundur(tmp_path, "e1", "e2")

    assert store.kirim_ulang_sekarang() == 2
    assert sorted(r["event_id"] for r in store.get_pending()) == ["e1", "e2"]


def test_riwayat_percobaan_dan_galat_tetap_terbaca(tmp_path):
    store = _store_mundur(tmp_path, "e1")

    store.kirim_ulang_sekarang()

    baris = store._db.execute("SELECT retry_count, last_error, status FROM outbox_events").fetchone()
    assert (baris["retry_count"], baris["last_error"], baris["status"]) == (4, "HTTP 503: konsol sibuk", "pending")


def test_janjang_baru_tetap_didahulukan_sesudah_kirim_ulang(tmp_path):
    store = _store_mundur(tmp_path, "lama")
    store.add_event("baru", "m1", {"event_id": "baru"})

    store.kirim_ulang_sekarang()

    assert [r["event_id"] for r in store.get_pending()] == ["baru", "lama"]


def test_mengulang_aman(tmp_path):
    store = _store_mundur(tmp_path, "e1")
    store.kirim_ulang_sekarang()

    assert store.kirim_ulang_sekarang() == 1
    assert store.pending_count() == 1
