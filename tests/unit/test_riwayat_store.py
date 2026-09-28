"""Query tab Riwayat di atas `console.db` sungguhan (SQLite di folder sementara).

Yang dijaga:

- angka per hari / per truk / per janjang benar dan urut terbaru dulu;
- **satu hari di Riwayat = tab Rekap hari itu** (query berbeda, angka harus sama);
- neto per truk dijumlah, tidak dikalikan jumlah janjang (jebakan JOIN aturan 17);
- saringan plat memakai aturan normalisasi yang sama dengan timbangan;
- query berjalan di koneksinya sendiri: tidak menunggu lock konsol yang dipakai
  menulis janjang dari line.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from palmgrade.domain.riwayat import FilterRiwayat, ringkas_periode
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.riwayat_repository import RiwayatStore

T1, T2 = "truk-1", "truk-2"


def _janjang(event_id, work_date, jam, *, line="line-1", truk=T1, kelas="Ripe", tp=None,
             status=None, capture="auto"):
    verdict = status or ("ACC" if kelas == "Ripe" or kelas is None else "REJ")
    return {
        "event_id": event_id, "machine_id": "m-1", "line_code": line, "work_date": work_date,
        "timestamp": f"{work_date}T{jam}+07:00", "ripeness_status": verdict,
        "ripeness_confidence": 0.9, "capture_type": capture,
        "image_path": f"captures/results/{work_date}/{event_id}.webp", "truck_id": truk,
        "assignment_id": f"a-{truk}-{work_date}", "prediction": "Acc" if verdict == "ACC" else "Rej",
        "grade_class": kelas, "tp_status": None, "tp_confidence": tp,
    }


@pytest.fixture
def konsol(tmp_path) -> ConsoleStore:
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_supplier({"id": "s-1", "name": "=PT Sawit", "source_group": "Plasma",
                           "status": "active"})
    store.upsert_truck({"id": T1, "plate_number": "BE 1234 AB", "supplier_id": "s-1",
                        "status": "active"})
    store.upsert_truck({"id": T2, "plate_number": "BE 9999 CD", "status": "active",
                        "erp_name": "TRK-2"})
    baris = [
        # 24 Sep: T1 di line-1 (2 Ripe, 1 JK), T2 di line-2 (1 Unripe)
        _janjang("e1", "2026-09-24", "08:00:00", kelas="Ripe", tp=0.95),
        _janjang("e2", "2026-09-24", "08:01:00", kelas="Ripe"),
        _janjang("e3", "2026-09-24", "08:02:00", kelas="JK"),
        _janjang("e4", "2026-09-24", "09:00:00", line="line-2", truk=T2, kelas="Unripe"),
        # 25 Sep: T1 (1 Ripe) + janjang tanpa truk (baris lama tanpa kelas)
        _janjang("e5", "2026-09-25", "10:00:00", kelas="Ripe"),
        _janjang("e6", "2026-09-25", "07:00:00", truk=None, kelas=None, status="ACC"),
        # 26 Sep: T2 (1 Ripe, 1 reject manual tanpa kelas)
        _janjang("e7", "2026-09-26", "11:00:00", line="line-2", truk=T2, kelas="Ripe", tp=0.5),
        _janjang("e8", "2026-09-26", "11:05:00", line="line-2", truk=T2, kelas=None,
                 status="REJ", capture="manual"),
        # 10 Sep: di luar rentang tes
        _janjang("e9", "2026-09-10", "08:00:00", kelas="Ripe"),
    ]
    for row in baris:
        store.add_inspection(row)
    # T1 datang dua kali tanggal 24: dua tiket, neto dijumlah (bukan dikali janjang).
    for wid, truk, tgl, neto in (
        ("w1", T1, "2026-09-24", 5000.0), ("w2", T1, "2026-09-24", 2500.0),
        ("w3", T2, "2026-09-24", 7000.0), ("w4", T1, "2026-09-25", 4000.0),
        ("w5", T2, "2026-09-26", None),  # belum timbang keluar
    ):
        store.upsert_weighing({
            "id": wid, "ref": None, "plate_number": None, "plate_norm": None, "truck_id": truk,
            "work_date": tgl, "gross_kg": 9000.0, "tare_kg": None if neto is None else 1.0,
            "net_kg": neto, "entered_at": f"{tgl}T07:00:00+07:00", "exited_at": None,
        })
    return store


@pytest.fixture
def riwayat(konsol, tmp_path) -> RiwayatStore:
    return RiwayatStore(tmp_path / "console.db")


F = FilterRiwayat(dari="2026-09-20", sampai="2026-09-26")


def _ringkasan(riwayat, f):
    return ringkas_periode(riwayat.hari(f), per_line=bool(f.line_code))


def test_ringkasan_satu_periode(riwayat):
    r = _ringkasan(riwayat, F)

    assert r == {
        "total": 8, "acc": 5, "rej": 3, "ripe": 4, "unripe": 1, "jk": 1, "tanpa_kelas": 2,
        "tp": 1, "hari": 3, "truk": 4, "neto_kg": 18500.0,
    }


def test_ringkasan_periode_kosong_nol_bukan_none(riwayat):
    r = _ringkasan(riwayat, FilterRiwayat(dari="2026-01-01", sampai="2026-01-05"))

    assert r["total"] == 0 and r["ripe"] == 0 and r["hari"] == 0
    assert r["neto_kg"] is None


def test_neto_tidak_ditampilkan_saat_disaring_per_line(riwayat):
    """Neto itu berat truk, bukan milik satu line; angka neto "line-1" akan bohong."""
    r = _ringkasan(riwayat, FilterRiwayat(dari="2026-09-20", sampai="2026-09-26", line_code="line-1"))

    assert r["total"] == 5  # e1, e2, e3, e5, e6
    assert r["neto_kg"] is None


def test_per_hari_terbaru_dulu_dengan_neto_hari_itu(riwayat):
    items = riwayat.hari(F)

    assert [i["work_date"] for i in items] == ["2026-09-26", "2026-09-25", "2026-09-24"]
    hari24 = items[2]
    assert (hari24["total"], hari24["ripe"], hari24["jk"], hari24["unripe"], hari24["tp"]) == (4, 2, 1, 1, 1)
    assert hari24["truk"] == 2
    assert hari24["neto_kg"] == 14500.0
    # Tiket belum timbang keluar tidak dihitung sebagai nol kg.
    assert items[0]["neto_kg"] is None


def test_hari_dengan_tiket_tanpa_janjang_tetap_muncul(konsol, riwayat):
    """Kamera mati seharian: truk tetap ditimbang, janjangnya nol. Hari itu harus
    terlihat, dan netonya masuk ringkasan periode."""
    konsol.upsert_weighing({
        "id": "w9", "ref": None, "plate_number": None, "plate_norm": None, "truck_id": T1,
        "work_date": "2026-09-22", "gross_kg": 9000.0, "tare_kg": 1.0, "net_kg": 1000.0,
        "entered_at": "2026-09-22T07:00:00+07:00", "exited_at": None,
    })

    items = riwayat.hari(F)
    ringkas = _ringkasan(riwayat, F)

    assert len(items) == 4
    hari22 = items[-1]
    assert (hari22["work_date"], hari22["total"], hari22["neto_kg"]) == ("2026-09-22", 0, 1000.0)
    assert ringkas["neto_kg"] == 19500.0 and ringkas["hari"] == 4


def test_per_truk_satu_baris_per_truk_per_hari_dengan_neto_dijumlah(riwayat):
    items = riwayat.truk(F)

    # Janjang tanpa truk tetap satu baris sendiri ("Tanpa truk"), seperti Rekap.
    assert len(items) == 5
    kunci = [(i["work_date"], i["truck_id"]) for i in items]
    assert kunci == [("2026-09-26", T2), ("2026-09-25", T1), ("2026-09-25", None),
                     ("2026-09-24", T2), ("2026-09-24", T1)]
    t1_24 = next(i for i in items if i["work_date"] == "2026-09-24" and i["truck_id"] == T1)
    # Dua tiket (5000 + 2500), bukan 3 janjang x 7500.
    assert t1_24["neto_kg"] == 7500.0
    assert (t1_24["total"], t1_24["ripe"], t1_24["jk"], t1_24["plate_number"]) == (3, 2, 1, "BE 1234 AB")
    assert t1_24["supplier_name"] == "=PT Sawit"
    tanpa = next(i for i in items if i["truck_id"] is None)
    assert tanpa["neto_kg"] is None and tanpa["tanpa_kelas"] == 1


def test_per_truk_urut_tanggal_lalu_jam_terakhir(riwayat):
    items = riwayat.truk(F)

    assert items[0]["work_date"] == "2026-09-26"
    hari25 = [i["truck_id"] for i in items if i["work_date"] == "2026-09-25"]
    # T1 terakhir digrading 10:00, janjang tanpa truk 07:00: yang terbaru di atas.
    assert hari25 == [T1, None]


def test_satu_hari_di_riwayat_sama_dengan_tab_rekap(konsol, riwayat):
    """Dua query berbeda untuk angka yang sama: operator akan membandingkannya."""
    hari = "2026-09-24"
    rekap = {r["truck_id"]: r for r in konsol.truck_recap(hari)}
    items = riwayat.truk(FilterRiwayat(dari=hari, sampai=hari))

    assert {i["truck_id"] for i in items} == set(rekap)
    for i in items:
        r = rekap[i["truck_id"]]
        for kolom in ("total", "acc", "rej", "ripe", "unripe", "jk", "tanpa_kelas", "tp"):
            assert i[kolom] == r[kolom], (i["truck_id"], kolom)


def test_per_janjang_terbaru_dulu_lintas_hari_dengan_total(riwayat):
    items, total = riwayat.janjang(F, limit=3, offset=0)

    assert total == 8
    assert [i["event_id"] for i in items] == ["e8", "e7", "e5"]
    assert items[0]["plate_number"] == "BE 9999 CD"
    assert "erp_state" not in items[0]


def test_per_janjang_disaring_hasil(riwayat):
    jk, total_jk = riwayat.janjang(
        FilterRiwayat(dari="2026-09-20", sampai="2026-09-26", hasil="jk"), limit=25, offset=0)
    tp, total_tp = riwayat.janjang(
        FilterRiwayat(dari="2026-09-20", sampai="2026-09-26", hasil="tp"), limit=25, offset=0)

    assert ([i["event_id"] for i in jk], total_jk) == (["e3"], 1)
    # Ambang TP sama dengan Rekap: 0,5 tidak dihitung.
    assert ([i["event_id"] for i in tp], total_tp) == (["e1"], 1)


def test_saringan_plat_memakai_potongan_plat_ternormalisasi(riwayat):
    f = FilterRiwayat(dari="2026-09-20", sampai="2026-09-26", plat="BE1234")

    items, total = riwayat.janjang(f, limit=25, offset=0)
    ringkas = _ringkasan(riwayat, f)

    assert total == 4 and {i["truck_id"] for i in items} == {T1}
    assert ringkas["neto_kg"] == 11500.0


def test_saringan_plat_tanpa_truk_cocok_berarti_kosong_bukan_error(riwayat):
    f = FilterRiwayat(dari="2026-09-20", sampai="2026-09-26", plat="ZZZ")

    assert riwayat.janjang(f, limit=25, offset=0) == ([], 0)
    assert riwayat.hari(f) == [] and riwayat.truk(f) == []
    assert _ringkasan(riwayat, f)["total"] == 0


def test_saringan_line(riwayat):
    f = FilterRiwayat(dari="2026-09-20", sampai="2026-09-26", line_code="line-2")

    _, total = riwayat.janjang(f, limit=25, offset=0)
    items = riwayat.hari(f)

    assert total == 3
    assert all(i["neto_kg"] is None for i in items)


def test_semua_baris_untuk_csv_tidak_terpotong_halaman(riwayat):
    assert len(list(riwayat.semua_janjang(F))) == 8


def test_koneksi_baca_saja(riwayat):
    with riwayat._baca() as db, pytest.raises(sqlite3.OperationalError):
        db.execute("DELETE FROM inspections")


def test_tidak_menunggu_lock_konsol(konsol, riwayat):
    """Lock konsol dipegang tiap janjang yang dikirim line. Riwayat sebulan yang
    antre di belakangnya akan menahan grading; sebaliknya juga."""
    hasil = {}

    def baca():
        hasil["r"] = _ringkasan(riwayat, F)

    with konsol._lock:
        t = threading.Thread(target=baca)
        t.start()
        t.join(timeout=5)

    assert not t.is_alive(), "Riwayat menunggu lock konsol"
    assert hasil["r"]["total"] == 8
