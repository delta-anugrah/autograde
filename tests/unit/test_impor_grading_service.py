"""Impor grading (support): periksa dulu, lalu impor berkas yang SAMA, dan bisa dibatalkan.

- Periksa tidak menyimpan apa pun: angka baru / sudah ada / hari berjalan / salah.
- Impor menolak berkas yang berubah sejak diperiksa (sidik), berkas dengan baris salah,
  dan berkas tanpa janjang baru. Satu impor pada satu waktu.
- Janjang hari ini dan sesudahnya tidak pernah diimpor: masih berjalan di pabrik dan
  ikut kunjungan truk yang dikirim ke AutoERP.
- Batal menghapus janjang batch itu saja; truk yang dibuat impor tetap ada.
"""
from __future__ import annotations

import csv
import io
import itertools
import logging

import pytest

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.bahaya import MODE_TRANSAKSI
from palmgrade.domain.impor_grading import sidik
from palmgrade.domain.operator_error import (
    IMPOR_ADA_SALAH,
    IMPOR_BERJALAN,
    IMPOR_HAPUS_BERJALAN,
    IMPOR_SIDIK_BEDA,
    IMPOR_SUDAH_DIBATALKAN,
    IMPOR_TERLALU_BESAR,
    IMPOR_TIDAK_ADA,
    IMPOR_TIDAK_ADA_BARU,
    InvalidInput,
    OperatorError,
)
from palmgrade.domain.plate import truck_id_for
from palmgrade.domain.riwayat import KEPALA_CSV
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services import impor_grading_service as modul
from palmgrade.services.impor_grading_service import ImporGradingService

MESIN_1 = "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01"
LINES = (LineEndpoint("line-1", "Line 1", 8001, MESIN_1),)
HARI_INI = "2026-09-27"
OLEH = "support@pks.id"


class _Jam:
    now = 1_790_500_000.0

    def __call__(self) -> float:
        return self.now


def _event(n: int) -> str:
    return f"00000000-0000-5000-8000-{n:012d}"


def _baris(n: int, **ganti: str) -> dict[str, str]:
    isi = {
        "Tanggal kerja": "2026-09-24", "Waktu": "2026-09-24 08:00:00", "Line": "line-1",
        "Plat": "BE 1234 AB", "Supplier": "CV Maju", "Sumber": "Eksternal", "Kelas": "Ripe",
        "Hasil": "ACC", "TP": "", "Jenis": "otomatis", "Foto": "", "Event ID": _event(n),
    }
    isi.update(ganti)
    return isi


def _csv(*baris: dict[str, str]) -> bytes:
    buffer = io.StringIO()
    penulis = csv.DictWriter(buffer, fieldnames=KEPALA_CSV["janjang"]["id"], lineterminator="\r\n")
    penulis.writeheader()
    penulis.writerows(baris)
    return ("﻿" + buffer.getvalue()).encode()


def _asli(store: ConsoleStore, n: int, work_date: str = "2026-09-24") -> None:
    store.add_inspection({
        "event_id": _event(n), "machine_id": MESIN_1, "line_code": "line-1", "work_date": work_date,
        "timestamp": f"{work_date}T01:00:00+00:00", "ripeness_status": "REJ", "ripeness_confidence": 0.9,
        "capture_type": "auto", "image_path": None, "truck_id": None, "assignment_id": None,
        "prediction": "Rej", "grade_class": "JK", "tp_status": None, "tp_confidence": None,
    })


def _janjang(store: ConsoleStore) -> dict[str, dict]:
    return {r["event_id"]: dict(r) for r in store._db.execute("SELECT * FROM inspections")}


@pytest.fixture
def store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


@pytest.fixture
def service(store) -> ImporGradingService:
    nomor = itertools.count(1)
    return ImporGradingService(
        store, lines=LINES, zona="Asia/Jakarta", hari_ini=lambda: HARI_INI, jam=_Jam(),
        id_baru=lambda: f"b{next(nomor)}",
    )


def _galat(fungsi, *args, **kwargs) -> OperatorError:
    with pytest.raises(OperatorError) as galat:
        fungsi(*args, **kwargs)
    return galat.value


# ── periksa ───────────────────────────────────────────────────────────────


def test_periksa_menghitung_tanpa_menyimpan_apa_pun(store, service):
    _asli(store, 1)
    isi = _csv(
        _baris(1),                                                     # sudah ada
        _baris(2), _baris(3, **{"Tanggal kerja": "2026-09-25", "Waktu": "2026-09-25 09:00:00"}),
        _baris(3, **{"Tanggal kerja": "2026-09-25", "Waktu": "2026-09-25 09:00:00"}),  # ganda
        _baris(4, **{"Tanggal kerja": HARI_INI, "Waktu": f"{HARI_INI} 07:00:00"}),      # hari ini
    )

    p = service.periksa(isi, nama_berkas="riwayat.csv")

    assert (p["baris"], p["baru"], p["sudah_ada"], p["ganda"], p["hari_berjalan"], p["salah"]) == (
        5, 2, 1, 1, 1, 0
    )
    assert (p["dari"], p["sampai"], p["bisa_impor"], p["sidik"]) == ("2026-09-24", "2026-09-25", True, sidik(isi))
    assert p["per_line"] == [{"line_code": "line-1", "jumlah": 2, "dikenal": True}]
    assert (p["truk_baru"], p["truk_baru_jumlah"]) == (["BE 1234 AB"], 1)
    assert set(_janjang(store)) == {_event(1)}
    assert store.daftar_impor() == [] and store.trucks_semua() == []


def test_periksa_melaporkan_baris_salah_dan_impor_tidak_bisa(service):
    p = service.periksa(_csv(_baris(1), _baris(2, Hasil="OK")), nama_berkas="x.csv")

    assert (p["salah"], p["bisa_impor"]) == (1, False)
    assert p["contoh_salah"] == [{"nomor": 3, "kode": "hasil_tidak_sah", "params": {"nilai": "OK"}}]


def test_contoh_salah_dibatasi_tapi_jumlahnya_utuh(service):
    p = service.periksa(_csv(*[_baris(n, Hasil="OK") for n in range(60)]), nama_berkas="x.csv")

    assert (p["salah"], len(p["contoh_salah"])) == (60, 50)


def test_line_asing_ditandai_di_pratinjau(service):
    p = service.periksa(_csv(_baris(1, Line="line-9")), nama_berkas="x.csv")

    assert p["per_line"] == [{"line_code": "line-9", "jumlah": 1, "dikenal": False}]


def test_berkas_terlalu_besar_ditolak_sebelum_dibaca(service, monkeypatch):
    monkeypatch.setattr(modul, "MAKS_BYTE", 10)

    with pytest.raises(InvalidInput) as galat:
        service.periksa(_csv(_baris(1)), nama_berkas="x.csv")

    assert (galat.value.code, galat.value.params["maks_mb"]) == (IMPOR_TERLALU_BESAR, 0)


# ── impor ─────────────────────────────────────────────────────────────────


def test_impor_menyimpan_janjang_utuh_dan_membuat_truknya(store, service):
    store.upsert_supplier({"id": "s1", "name": "CV Maju", "source_group": "Eksternal", "status": "active"})
    isi = _csv(
        _baris(1, TP="ya", Foto="/captures/line-1/results/2026-09-24/a.webp"),
        _baris(2, Kelas="JK", Hasil="REJ", Jenis="manual", Plat="", Supplier=""),
    )

    batch = service.impor(isi, nama_berkas="riwayat.csv", sidik=sidik(isi), oleh=OLEH)

    rows = _janjang(store)
    satu, dua = rows[_event(1)], rows[_event(2)]
    assert (satu["machine_id"], satu["timestamp"], satu["work_date"]) == (
        MESIN_1, "2026-09-24T01:00:00+00:00", "2026-09-24"
    )
    assert (satu["ripeness_status"], satu["prediction"], satu["grade_class"]) == ("ACC", "Acc", "Ripe")
    assert (satu["tp_status"], satu["tp_confidence"]) == ("PASS", 1.0)
    assert (satu["image_path"], satu["truck_id"], satu["assignment_id"]) == (
        "captures/results/2026-09-24/a.webp", truck_id_for("BE 1234 AB"), None
    )
    assert (dua["prediction"], dua["capture_type"], dua["truck_id"], dua["tp_confidence"]) == (
        "Rej", "manual", None, None
    )
    assert {r["import_batch"] for r in rows.values()} == {"b1"}
    truk = store.truck(truck_id_for("BE 1234 AB"))
    assert (truk["plate_number"], truk["supplier_id"], truk["status"]) == ("BE 1234 AB", "s1", "manual")
    assert (batch["id"], batch["status"], batch["added"], batch["new_trucks"], batch["imported_by"]) == (
        "b1", "done", 2, 1, OLEH
    )
    assert (batch["date_from"], batch["date_to"], batch["file_name"]) == ("2026-09-24", "2026-09-24", "riwayat.csv")


def test_truk_yang_sudah_ada_dipakai_bukan_dibuat_ulang(store, service):
    store.upsert_truck({"id": "acak-lama", "plate_number": "be-1234-ab", "status": "manual"})
    isi = _csv(_baris(1))

    batch = service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    assert _janjang(store)[_event(1)]["truck_id"] == "acak-lama"
    assert (batch["new_trucks"], len(store.trucks_semua())) == (0, 1)


def test_hari_ini_tidak_diimpor_dan_yang_sudah_ada_tidak_disentuh(store, service):
    _asli(store, 1)
    isi = _csv(_baris(1), _baris(2), _baris(3, **{"Tanggal kerja": HARI_INI, "Waktu": f"{HARI_INI} 07:00:00"}))

    batch = service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    rows = _janjang(store)
    assert set(rows) == {_event(1), _event(2)}
    assert (rows[_event(1)]["grade_class"], rows[_event(1)]["import_batch"]) == ("JK", None)
    assert (batch["added"], batch["skipped_existing"], batch["skipped_today"]) == (1, 1, 1)


def test_impor_ditolak_kalau_berkas_berubah_sejak_diperiksa(store, service):
    isi = _csv(_baris(1))

    galat = _galat(service.impor, isi, nama_berkas="x.csv", sidik=sidik(b"lain"), oleh=OLEH)

    assert galat.code == IMPOR_SIDIK_BEDA
    assert store.daftar_impor() == []


def test_impor_ditolak_utuh_kalau_ada_satu_baris_salah(store, service):
    isi = _csv(_baris(1), _baris(2, Kelas="Unripe", Hasil="ACC"))

    galat = _galat(service.impor, isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    assert (galat.code, galat.params["jumlah"]) == (IMPOR_ADA_SALAH, 1)
    assert _janjang(store) == {} and store.daftar_impor() == []


def test_impor_ulang_berkas_yang_sama_tidak_ada_yang_baru(store, service):
    isi = _csv(_baris(1))
    service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    galat = _galat(service.impor, isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    assert galat.code == IMPOR_TIDAK_ADA_BARU
    assert len(store.daftar_impor()) == 1


def test_satu_impor_pada_satu_waktu(service):
    isi = _csv(_baris(1))
    with service._kunci:
        galat = _galat(service.impor, isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    assert galat.code == IMPOR_BERJALAN


def test_danger_zone_yang_sedang_menghapus_menolak_impor_dan_batal(store, service):
    isi = _csv(_baris(1))
    batch = service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)
    store.hapus_berjalan = True

    assert _galat(service.impor, _csv(_baris(2)), nama_berkas="x.csv",
                  sidik=sidik(_csv(_baris(2))), oleh=OLEH).code == IMPOR_HAPUS_BERJALAN
    assert _galat(service.batalkan, batch["id"], oleh=OLEH).code == IMPOR_HAPUS_BERJALAN


def test_danger_zone_di_tengah_impor_menghentikannya(store):
    """Dicek sebelum tiap potongan: janjang yang ditulis sesudah penghapusan mulai
    akan tersisa sebagai data setengah-impor di pabrik yang baru dikosongkan."""
    potongan = []
    asli = store.simpan_potongan_impor

    def simpan(*args, **kwargs):
        potongan.append(1)
        hasil = asli(*args, **kwargs)
        store.hapus_berjalan = True
        return hasil

    store.simpan_potongan_impor = simpan
    service = ImporGradingService(store, lines=LINES, zona="Asia/Jakarta", hari_ini=lambda: HARI_INI,
                                  jam=_Jam(), id_baru=lambda: "b1", potong=2)
    isi = _csv(*[_baris(n) for n in range(5)])

    galat = _galat(service.impor, isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    assert (galat.code, len(potongan)) == (IMPOR_HAPUS_BERJALAN, 1)
    assert store.impor_grading("b1")["status"] == "interrupted"


def test_danger_zone_yang_selesai_selama_berkas_diperiksa_tetap_menghentikan_impor(store):
    """Memeriksa 50 MB bisa lebih dari 10 detik, lebih lama dari satu penghapusan Danger
    Zone. Penghapusan yang mulai DAN selesai di jendela itu tidak boleh terlewat: impornya
    akan mengisi pabrik yang baru saja dikosongkan."""
    asli = store.event_sudah_ada
    dihapus = []

    def sambil_dihapus(ids):
        if not dihapus:
            dihapus.append(1)
            store.hapus_data(MODE_TRANSAKSI)
        return asli(ids)

    store.event_sudah_ada = sambil_dihapus
    service = ImporGradingService(store, lines=LINES, zona="Asia/Jakarta", hari_ini=lambda: HARI_INI,
                                  jam=_Jam(), id_baru=lambda: "b1")
    isi = _csv(_baris(1), _baris(2))

    galat = _galat(service.impor, isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    assert galat.code == IMPOR_HAPUS_BERJALAN
    assert store.daftar_impor() == [] and _janjang(store) == {}


def test_galat_di_tengah_impor_meninggalkan_batch_terputus_yang_bisa_dibatalkan(store):
    panggilan = []
    asli = store.simpan_potongan_impor

    def simpan(*args, **kwargs):
        panggilan.append(1)
        if len(panggilan) == 2:
            raise OSError("disk penuh")
        return asli(*args, **kwargs)

    store.simpan_potongan_impor = simpan
    service = ImporGradingService(store, lines=LINES, zona="Asia/Jakarta", hari_ini=lambda: HARI_INI,
                                  jam=_Jam(), id_baru=lambda: "b1", potong=2)
    isi = _csv(*[_baris(n) for n in range(5)])

    with pytest.raises(OSError):
        service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)
    batch = service.batalkan("b1", oleh=OLEH)

    assert (batch["status"], batch["removed"]) == ("undone", 2)
    assert _janjang(store) == {}
    # Truk yang terlanjur dibuat potongan pertama tetap tercatat, walau impornya terputus.
    assert batch["new_trucks"] == 1


def test_batal_memberi_giliran_ke_ingest_di_antara_potongan(store):
    """Lock konsol tidak antre: tanpa jeda, pembatalan besar merebut lock lagi sebelum
    ingest janjang dari line (di loop asyncio) sempat masuk, dan layar ikut membeku."""
    jeda = []
    service = ImporGradingService(store, lines=LINES, zona="Asia/Jakarta", hari_ini=lambda: HARI_INI,
                                  jam=_Jam(), id_baru=lambda: "b1", potong_batal=2, jeda=jeda.append)
    isi = _csv(*[_baris(n) for n in range(5)])
    service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    batch = service.batalkan("b1", oleh=OLEH)

    assert batch["removed"] == 5
    assert len(jeda) == 3 and all(0 < d <= 0.05 for d in jeda)


# ── batal ─────────────────────────────────────────────────────────────────


def test_batal_menghapus_janjang_impor_saja_dan_truknya_tetap(store, service):
    _asli(store, 99)
    isi = _csv(_baris(1), _baris(2))
    batch = service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    hasil = service.batalkan(batch["id"], oleh="lain@pks.id")

    assert set(_janjang(store)) == {_event(99)}
    assert (hasil["status"], hasil["removed"], hasil["undone_by"]) == ("undone", 2, "lain@pks.id")
    assert store.truck(truck_id_for("BE 1234 AB")) is not None
    assert _galat(service.batalkan, batch["id"], oleh=OLEH).code == IMPOR_SUDAH_DIBATALKAN
    assert _galat(service.batalkan, "tidak-ada", oleh=OLEH).code == IMPOR_TIDAK_ADA


def test_sesudah_batal_berkas_yang_sama_bisa_diimpor_lagi(store, service):
    isi = _csv(_baris(1))
    service.batalkan(service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)["id"], oleh=OLEH)

    batch = service.impor(isi, nama_berkas="x.csv", sidik=sidik(isi), oleh=OLEH)

    assert (batch["id"], batch["added"]) == ("b2", 1)


def test_daftar_impor_terbaru_dulu(service):
    for n in (1, 2):
        isi = _csv(_baris(n))
        service.impor(isi, nama_berkas=f"{n}.csv", sidik=sidik(isi), oleh=OLEH)

    assert [b["file_name"] for b in service.daftar()["items"]] == ["2.csv", "1.csv"]


def test_konsol_menyala_menandai_impor_yang_terputus(store):
    store.mulai_impor({"id": "lama", "file_name": "x.csv", "fingerprint": "f", "imported_by": OLEH,
                       "started_at": 1.0, "rows_total": 1})

    ImporGradingService(store, lines=LINES, zona="Asia/Jakarta", hari_ini=lambda: HARI_INI)

    assert store.impor_grading("lama")["status"] == "interrupted"


def test_impor_dan_batal_dicatat_sekali_di_log(service, caplog):
    isi = _csv(_baris(1), _baris(2))
    with caplog.at_level(logging.WARNING, logger="palmgrade.services.impor_grading_service"):
        batch = service.impor(isi, nama_berkas="riwayat.csv", sidik=sidik(isi), oleh=OLEH)
        service.batalkan(batch["id"], oleh=OLEH)

    pesan = [r.getMessage() for r in caplog.records]
    assert len(pesan) == 2, pesan
    assert "riwayat.csv" in pesan[0] and OLEH in pesan[0] and "2 janjang" in pesan[0]
    assert "dibatalkan" in pesan[1] and "2 janjang" in pesan[1]
