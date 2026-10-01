"""Antrean bongkar: tiket yang sudah timbang isi, belum timbang kosong, dan belum pernah di line."""
from __future__ import annotations

import sqlite3
import time

from palmgrade.repositories.console_repository import ConsoleStore

HARI = "2026-10-01"


def _tiket(store, wid, truck, *, tara=None):
    store.upsert_weighing({
        "id": wid, "ref": None, "plate_number": f"BE {truck}", "plate_norm": f"BE{truck}",
        "truck_id": truck, "work_date": HARI, "gross_kg": 14000.0, "tare_kg": tara,
        "net_kg": None if tara is None else 14000.0 - tara,
        "entered_at": f"{HARI}T01:00:00+00:00", "exited_at": None,
    })


def _sejak():
    return time.time() - 3600


def test_antrean_urut_timbang_isi(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    _tiket(store, "w2", "B")
    assert [r["weighing_id"] for r in store.unloading_queue(_sejak())] == ["w1", "w2"]


def test_antrean_membawa_kunci_yang_dibaca_penugasan(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    [baris] = store.unloading_queue(_sejak())
    assert set(baris) == {"weighing_id", "truck_id", "plate_number", "entered_at", "received_at"}
    assert (baris["weighing_id"], baris["truck_id"], baris["plate_number"]) == ("w1", "A", "BE A")


def test_tiket_yang_sudah_timbang_kosong_tidak_antre(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A", tara=6000.0)
    assert store.unloading_queue(_sejak()) == []


def test_truk_yang_sedang_di_line_tidak_antre(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    store.set_assignment("line-1", "as-1", "A")
    assert store.unloading_queue(_sejak()) == []


def test_cuma_tiket_terbaru_satu_truk_yang_antre(tmp_path):
    """Truk yang tertimbang isi dua kali karena salah: tiket lamanya tidak pernah antre
    sendiri, jadi truk itu tidak naik lagi ke line lewat tiket yang terlupa."""
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    _tiket(store, "w2", "B")
    _tiket(store, "w3", "A")
    assert [r["weighing_id"] for r in store.unloading_queue(_sejak())] == ["w2", "w3"]


def test_truk_yang_pernah_di_line_tidak_antre_lagi(tmp_path):
    """Dilepas manual sebelum timbang kosong: sudah disortir, jangan ditugaskan ulang."""
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    store.link_weighing_to_assignment("w1", "as-1", "line-1")
    assert store.unloading_queue(_sejak()) == []


def test_tiket_lama_di_luar_jendela_tidak_antre(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    assert store.unloading_queue(time.time() + 1) == []


def test_lewati_mengeluarkan_dari_antrean_sekali_saja(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    assert store.skip_unloading_queue("w1", f"{HARI}T01:05:00+07:00") is True
    assert store.skip_unloading_queue("w1", f"{HARI}T01:06:00+07:00") is False
    assert store.unloading_queue(_sejak()) == []


def test_lewati_hanya_menyingkirkan_tiket_itu(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    _tiket(store, "w2", "B")
    store.skip_unloading_queue("w1", f"{HARI}T01:05:00+07:00")
    assert [r["weighing_id"] for r in store.unloading_queue(_sejak())] == ["w2"]


def test_tiket_selesai_tidak_bisa_dilewati(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A", tara=6000.0)
    assert store.skip_unloading_queue("w1", f"{HARI}T01:05:00+07:00") is False


def test_tiket_yang_tidak_ada_tidak_bisa_dilewati(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    assert store.skip_unloading_queue("tidak-ada", f"{HARI}T01:05:00+07:00") is False


def test_tanda_lewati_selamat_dari_timbang_ulang_tiket(tmp_path):
    """`upsert_weighing` tidak menyentuh kolom ini: tara yang masuk tidak menghapus tandanya."""
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    store.skip_unloading_queue("w1", f"{HARI}T01:05:00+07:00")
    _tiket(store, "w1", "A", tara=6000.0)
    assert store.weighing("w1")["unloading_queue_skipped_at"] == f"{HARI}T01:05:00+07:00"


def test_truk_dengan_tiket_terbuka(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    _tiket(store, "w2", "B", tara=6000.0)
    assert store.trucks_with_open_ticket(_sejak()) == {"A"}


def test_truk_dengan_tiket_terbuka_menghormati_jendela(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store, "w1", "A")
    assert store.trucks_with_open_ticket(time.time() + 1) == set()


def test_database_lama_mendapat_kolom_lewati_dan_aman_diulang(tmp_path):
    """Konsol pabrik yang sudah jalan: kolom ditambah saat boot, boot kedua tidak mengubah apa pun."""
    path = tmp_path / "console.db"
    lama = ConsoleStore(path)
    _tiket(lama, "w1", "A")
    with lama._lock, lama._db:
        lama._db.execute("ALTER TABLE weighings DROP COLUMN unloading_queue_skipped_at")
    lama._db.close()

    baru = ConsoleStore(path)
    assert [r["weighing_id"] for r in baru.unloading_queue(_sejak())] == ["w1"]
    baru._db.close()

    lagi = ConsoleStore(path)
    lagi.skip_unloading_queue("w1", f"{HARI}T01:05:00+07:00")
    lagi._db.close()
    kolom = [r[1] for r in sqlite3.connect(str(path)).execute("PRAGMA table_info(weighings)")]
    assert kolom.count("unloading_queue_skipped_at") == 1
