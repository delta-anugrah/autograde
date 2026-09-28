"""Impor grading di `ConsoleStore`: kolom `import_batch`, tabel `grading_imports`, dan
penulisan per potongan supaya lock konsol tidak tertahan lama.

Janjang hasil impor ditandai batch-nya: itu yang membuat satu impor bisa dibatalkan
utuh tanpa menyentuh janjang asli pabrik maupun impor lain.
"""
from __future__ import annotations

import sqlite3

import pytest

from palmgrade.domain.bahaya import MODE_TRANSAKSI
from palmgrade.domain.plate import truck_id_for
from palmgrade.repositories.console_repository import ConsoleStore


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _janjang(event_id: str, **ganti) -> dict:
    row = {
        "event_id": event_id, "machine_id": "m1", "line_code": "line-1", "work_date": "2026-09-24",
        "timestamp": "2026-09-24T01:00:00+00:00", "ripeness_status": "ACC", "ripeness_confidence": None,
        "capture_type": "auto", "image_path": None, "truck_id": None, "assignment_id": None,
        "received_at": 1.0, "prediction": "Acc", "grade_class": "Ripe", "tp_status": None,
        "tp_confidence": None,
    }
    row.update(ganti)
    return row


def _batch(store: ConsoleStore, batch_id: str = "b1", **ganti) -> None:
    store.mulai_impor({
        "id": batch_id, "file_name": "riwayat.csv", "fingerprint": "f" * 64,
        "imported_by": "support@pks.id", "started_at": 100.0, "rows_total": 3, **ganti,
    })


def _kolom(store: ConsoleStore, tabel: str) -> set[str]:
    return {r["name"] for r in store._db.execute(f"PRAGMA table_info({tabel})")}


def test_konsol_lama_mendapat_kolom_impor_tabel_dan_indeksnya(tmp_path):
    db = tmp_path / "lama.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE inspections (event_id TEXT PRIMARY KEY, machine_id TEXT NOT NULL,
               line_code TEXT NOT NULL, work_date TEXT NOT NULL, timestamp TEXT NOT NULL,
               ripeness_status TEXT NOT NULL, ripeness_confidence REAL, capture_type TEXT NOT NULL,
               image_path TEXT, truck_id TEXT, assignment_id TEXT, received_at REAL NOT NULL,
               prediction TEXT, tp_status TEXT, tp_confidence REAL, erp_state TEXT)"""
        )

    store = ConsoleStore(db)

    assert "import_batch" in _kolom(store, "inspections")
    assert {"id", "status", "added", "undone_by"} <= _kolom(store, "grading_imports")
    indeks = {r[0] for r in store._db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_inspections_impor" in indeks


def test_janjang_impor_ditandai_batch_dan_yang_sudah_ada_tidak_disentuh(store):
    store.add_inspection(_janjang("e-asli", ripeness_status="REJ", prediction="Rej", grade_class="JK"))
    _batch(store)

    ditambah, truk = store.simpan_potongan_impor("b1", [_janjang("e-asli"), _janjang("e-baru")], [])

    assert (ditambah, truk) == (1, 0)
    rows = {r["event_id"]: dict(r) for r in store._db.execute("SELECT * FROM inspections")}
    assert (rows["e-asli"]["grade_class"], rows["e-asli"]["import_batch"]) == ("JK", None)
    assert rows["e-baru"]["import_batch"] == "b1"


def test_event_yang_sudah_ada_dicari_per_potongan(store):
    store.add_inspection(_janjang("e1"))
    store.add_inspection(_janjang("e2"))

    assert store.event_sudah_ada(["e1", "e3", "e2"]) == {"e1", "e2"}
    assert store.event_sudah_ada([]) == set()


def test_truk_baru_dibuat_sekali_dan_truk_lama_tidak_diubah(store):
    store.upsert_truck({"id": truck_id_for("BE 1 AA"), "plate_number": "BE 1 AA", "supplier_id": "s-lama",
                        "status": "active", "erp_name": "TRK-1"})
    _batch(store)
    truk = [
        {"id": truck_id_for("BE 1 AA"), "plate_number": "BE 1 AA", "supplier_id": None},
        {"id": truck_id_for("BE 2 BB"), "plate_number": "BE 2 BB", "supplier_id": "s-1"},
    ]

    _, dibuat = store.simpan_potongan_impor("b1", [], truk)
    _, lagi = store.simpan_potongan_impor("b1", [], truk)

    assert (dibuat, lagi) == (1, 0)
    lama = store.truck(truck_id_for("BE 1 AA"))
    baru = store.truck(truck_id_for("BE 2 BB"))
    assert (lama["supplier_id"], lama["erp_name"]) == ("s-lama", "TRK-1")
    assert (baru["plate_number"], baru["supplier_id"], baru["status"]) == ("BE 2 BB", "s-1", "manual")


def test_peta_plat_memakai_truk_yang_sudah_ada_walau_id_lama_acak(store):
    """Truk warisan palmgrade-api ber-id acak (OPS-2). Impor tidak boleh membuat
    kembarannya: satu truk dua baris membelah tonase hari itu."""
    store.upsert_truck({"id": "acak-123", "plate_number": "be-1234 ab", "status": "manual"})

    assert store.peta_truk_per_plat() == {"BE1234AB": "acak-123"}


def test_supplier_dicari_per_nama_dan_nama_ganda_tidak_ditebak(store):
    store.upsert_supplier({"id": "s1", "name": "CV Maju", "source_group": "Eksternal", "status": "active"})
    store.upsert_supplier({"id": "s2", "name": "PT Sama", "source_group": "Eksternal", "status": "active"})
    store.upsert_supplier({"id": "s3", "name": " pt sama ", "source_group": "Eksternal", "status": "active"})

    assert store.supplier_per_nama() == {"cv maju": "s1", "pt sama": None}


def test_riwayat_impor_terbaru_dulu(store):
    _batch(store, "b1", started_at=100.0)
    _batch(store, "b2", started_at=200.0)
    store.selesai_impor("b1", status="done", finished_at=110.0, added=3, skipped_existing=1,
                        skipped_today=0, duplicates=0, date_from="2026-09-20", date_to="2026-09-24",
                        new_trucks=1)

    daftar = store.daftar_impor()

    assert [b["id"] for b in daftar] == ["b2", "b1"]
    assert (daftar[1]["status"], daftar[1]["added"], daftar[1]["date_to"]) == ("done", 3, "2026-09-24")
    assert store.impor_grading("tidak-ada") is None


def test_batal_menghapus_per_potong_hanya_janjang_batch_itu(store):
    store.add_inspection(_janjang("asli"))
    _batch(store, "b1")
    _batch(store, "b2")
    store.simpan_potongan_impor("b1", [_janjang(f"b1-{i}") for i in range(5)], [])
    store.simpan_potongan_impor("b2", [_janjang("b2-0")], [])

    potong = [store.hapus_potongan_impor("b1", batas=2) for _ in range(4)]
    store.tandai_impor_dibatalkan("b1", oleh="support@pks.id", now=300.0, removed=sum(potong))

    assert potong == [2, 2, 1, 0]
    sisa = {r[0] for r in store._db.execute("SELECT event_id FROM inspections")}
    assert sisa == {"asli", "b2-0"}
    b1 = store.impor_grading("b1")
    assert (b1["status"], b1["undone_by"], b1["undone_at"], b1["removed"]) == ("undone", "support@pks.id", 300.0, 5)


def test_impor_yang_masih_berjalan_saat_konsol_mati_ditandai_terputus(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    _batch(store, "b1")

    assert store.tandai_impor_terputus() == 1
    assert store.impor_grading("b1")["status"] == "interrupted"


def test_danger_zone_hapus_transaksi_ikut_mengosongkan_riwayat_impor(store):
    _batch(store)
    store.simpan_potongan_impor("b1", [_janjang("e1")], [])

    store.hapus_data(MODE_TRANSAKSI)

    assert store.daftar_impor() == []
    assert store.event_sudah_ada(["e1"]) == set()
