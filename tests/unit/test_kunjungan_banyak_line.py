"""Satu kunjungan, semua line yang membongkarnya (2026-10-01).

Truk di tiga line punya tiga penugasan. `weighings.assignment_id` cuma memegang satu,
jadi rekap ke AutoERP dan halaman detail dulu cuma menghitung line yang dilepas
terakhir. Yang dijumlah sekarang: semua penugasan yang tertaut ke kunjungan itu.
"""
from __future__ import annotations

import sqlite3

from palmgrade.domain.bahaya import GOLONGAN_TABEL_KONSOL
from palmgrade.repositories.console_repository import ConsoleStore

HARI = "2026-10-01"


def _tiket(store: ConsoleStore, wid: str = "w1") -> None:
    store.upsert_weighing({
        "id": wid, "ref": None, "plate_number": "BE 1 AA", "plate_norm": "BE1AA",
        "truck_id": "t1", "work_date": HARI, "gross_kg": 14000.0, "tare_kg": None,
        "net_kg": None, "entered_at": f"{HARI}T01:00:00+00:00", "exited_at": None,
    })


def _janjang(store: ConsoleStore, assignment_id: str, line_code: str, acc: int, rej: int) -> None:
    for i in range(acc + rej):
        tolak = i >= acc
        store.add_inspection({
            "event_id": f"{assignment_id}-{i}", "machine_id": f"m-{line_code}",
            "line_code": line_code, "work_date": HARI,
            "timestamp": f"{HARI}T01:{i:02d}:00+00:00",
            "ripeness_status": "REJ" if tolak else "ACC", "ripeness_confidence": 0.9,
            "capture_type": "auto", "image_path": None, "truck_id": "t1",
            "assignment_id": assignment_id, "prediction": "Rej" if tolak else "Acc",
            "tp_status": None, "tp_confidence": None,
        })


def test_rekap_kunjungan_menjumlah_semua_line(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store)
    _janjang(store, "a1", "line-1", acc=3, rej=1)
    _janjang(store, "a2", "line-2", acc=2, rej=0)
    _janjang(store, "a3", "line-3", acc=0, rej=2)
    for aid, line in (("a1", "line-1"), ("a2", "line-2"), ("a3", "line-3")):
        store.link_weighing_to_assignment("w1", aid, line)

    rekap = store.grading_counts_for_visit("w1")

    assert (rekap["total"], rekap["acc"], rekap["rej"]) == (8, 5, 3)
    assert rekap["line_code"] == "line-1, line-2, line-3"
    assert rekap["assignment_id"] == "a1", "kunci ke AutoERP harus tetap sama tiap kirim ulang"


def test_janjang_kunjungan_dari_semua_line_urut_waktu(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store)
    _janjang(store, "a1", "line-1", acc=2, rej=0)
    _janjang(store, "a2", "line-2", acc=1, rej=0)
    store.link_weighing_to_assignment("w1", "a1", "line-1")
    store.link_weighing_to_assignment("w1", "a2", "line-2")

    janjang = store.bunches_for_visit("w1")

    assert len(janjang) == 3
    assert [j["timestamp"] for j in janjang] == sorted(j["timestamp"] for j in janjang)


def test_kunjungan_tanpa_janjang_tidak_punya_rekap(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store)
    assert store.grading_counts_for_visit("w1") is None
    store.link_weighing_to_assignment("w1", "a1", "line-1")
    assert store.grading_counts_for_visit("w1") is None


def test_setiap_penugasan_menemukan_tiketnya(tmp_path):
    """Dulu cuma penugasan TERAKHIR yang menemukan tiketnya, jadi janjang susulan di
    line yang dilepas lebih dulu tidak pernah mengantre ulang kunjungannya."""
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store)
    store.link_weighing_to_assignment("w1", "a1", "line-1")
    store.link_weighing_to_assignment("w1", "a2", "line-2")
    assert store.weighing_for_assignment("a1") == "w1"
    assert store.weighing_for_assignment("a2") == "w1"
    assert store.weighing_for_assignment("asing") is None


def test_kolom_lama_tetap_ditulis_untuk_image_lama(tmp_path):
    """PC pabrik boleh mundur ke image lama, yang masih membaca `weighings.assignment_id`."""
    store = ConsoleStore(tmp_path / "console.db")
    _tiket(store)
    store.link_weighing_to_assignment("w1", "a1", "line-1")
    store.link_weighing_to_assignment("w1", "a2", "line-2")
    assert store.weighing("w1")["assignment_id"] == "a2"


def test_tautan_lama_terbawa_saat_konsol_baru_start(tmp_path):
    """Tiket yang ditautkan sebelum `visit_assignments` ada tetap terhitung."""
    db_path = tmp_path / "console.db"
    store = ConsoleStore(db_path)
    _tiket(store)
    _janjang(store, "a1", "line-1", acc=2, rej=1)
    store.link_weighing_to_assignment("w1", "a1", "line-1")
    with sqlite3.connect(db_path) as db:
        db.execute("DELETE FROM visit_assignments")   # keadaan sebelum tabel ini ada

    ulang = ConsoleStore(db_path)

    assert ulang.grading_counts_for_visit("w1")["total"] == 3


def test_tautan_digolongkan_transaksi_untuk_danger_zone():
    assert GOLONGAN_TABEL_KONSOL["visit_assignments"] == "transaksi"
