"""Layanan tab Riwayat: bentuk jawaban untuk layar dan isi berkas CSV.

- Janjang membawa `image_url` dan label Sumber yang sama dengan tab Grading;
  fakta mentah (`has_supplier`, `in_erp`) tidak ikut keluar.
- Per hari dan per truk dikirim utuh (layar yang membagi halaman), per janjang
  dibagi halaman di server.
- CSV: BOM supaya Excel membaca UTF-8, jam janjang dalam jam pabrik (bukan UTC),
  kepala kolom mengikuti bahasa layar, sel rumus dinetralkan, dan angka yang
  sama dengan layar.
"""

from __future__ import annotations

import csv
import io

import pytest

from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.riwayat_repository import RiwayatStore
from palmgrade.services.riwayat_service import RiwayatService

HARI_INI = "2026-09-26"


def _janjang(event_id, work_date, ts, *, truk="truk-1", kelas="Ripe", status="ACC", tp=None,
             capture="auto", line="line-1"):
    return {
        "event_id": event_id, "machine_id": "m-1", "line_code": line, "work_date": work_date,
        "timestamp": ts, "ripeness_status": status, "ripeness_confidence": 0.9,
        "capture_type": capture, "image_path": f"captures/results/{work_date}/{event_id}.webp",
        "truck_id": truk, "assignment_id": "a-1", "prediction": "Acc" if status == "ACC" else "Rej",
        "grade_class": kelas, "tp_status": None, "tp_confidence": tp,
    }


@pytest.fixture
def layanan(tmp_path) -> RiwayatService:
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_supplier({"id": "s-1", "name": "=HYPERLINK(\"x\")", "source_group": "Plasma",
                           "status": "active"})
    store.upsert_truck({"id": "truk-1", "plate_number": "BE 1234 AB", "supplier_id": "s-1",
                        "status": "active"})
    # 17:30 UTC tanggal 25 = 00:30 WIB tanggal 26: jam di CSV harus jam pabrik.
    store.add_inspection(_janjang("e1", "2026-09-25", "2026-09-25T17:30:00+00:00", tp=0.9))
    store.add_inspection(_janjang("e2", "2026-09-25", "2026-09-25T09:00:00+07:00", kelas="JK",
                                  status="REJ", capture="manual"))
    store.add_inspection(_janjang("e3", "2026-09-24", "2026-09-24T08:00:00+07:00"))
    store.upsert_weighing({
        "id": "w1", "ref": None, "plate_number": "BE 1234 AB", "plate_norm": "BE1234AB",
        "truck_id": "truk-1", "work_date": "2026-09-25", "gross_kg": 9000.0, "tare_kg": 2000.0,
        "net_kg": 7000.0, "entered_at": "2026-09-25T07:00:00+07:00", "exited_at": None,
    })
    return RiwayatService(RiwayatStore(tmp_path / "console.db"), hari_ini=lambda: HARI_INI,
                          zona="Asia/Jakarta")


def test_filter_bawaan_tujuh_hari_sampai_hari_ini(layanan):
    f = layanan.filter()

    assert (f.dari, f.sampai) == ("2026-09-20", "2026-09-26")


def test_halaman_membawa_rentang_dan_batasnya(layanan):
    hasil = layanan.halaman(layanan.filter(), tampilan="hari", limit=25, offset=0, ringkasan=False)

    assert (hasil["dari"], hasil["sampai"], hasil["hari_ini"], hasil["maks_hari"]) == (
        "2026-09-20", "2026-09-26", HARI_INI, 31)
    assert "ringkasan" not in hasil


def test_tampilan_hari_utuh_dengan_ringkasan_dari_pindaian_yang_sama(layanan):
    hasil = layanan.halaman(layanan.filter(), tampilan="hari", limit=1, offset=0, ringkasan=True)

    # Utuh: `limit` tidak memotong hari (paling banyak 31 baris).
    assert [h["work_date"] for h in hasil["items"]] == ["2026-09-25", "2026-09-24"]
    assert hasil["total"] == 2
    assert hasil["ringkasan"]["total"] == 3 and hasil["ringkasan"]["neto_kg"] == 7000.0


def test_tampilan_truk_berlabel_sumber_tanpa_fakta_mentah(layanan):
    hasil = layanan.halaman(layanan.filter(), tampilan="truk", limit=25, offset=0, ringkasan=False)

    baris = hasil["items"][0]
    assert baris["source_label"] == "External"
    assert "has_supplier" not in baris and "in_erp" not in baris
    assert baris["neto_kg"] == 7000.0


def test_tampilan_janjang_berhalaman_dengan_foto(layanan):
    hasil = layanan.halaman(layanan.filter(), tampilan="janjang", limit=2, offset=0, ringkasan=False)

    assert hasil["total"] == 3
    assert [j["event_id"] for j in hasil["items"]] == ["e1", "e2"]
    assert hasil["items"][0]["image_url"] == "/captures/line-1/results/2026-09-25/e1.webp"
    assert hasil["items"][0]["source_label"] == "External"
    assert "in_erp" not in hasil["items"][0]


def _csv(layanan, tampilan, bahasa="id", **filter_kw):
    nama, potongan = layanan.csv(layanan.filter(**filter_kw), tampilan=tampilan, bahasa=bahasa)
    isi = b"".join(potongan)
    return nama, isi


def test_csv_diawali_bom_supaya_excel_membaca_utf8(layanan):
    nama, isi = _csv(layanan, "hari")

    assert isi.startswith("﻿".encode())
    assert nama == "riwayat-grading-hari-2026-09-20_2026-09-26.csv"


def _baris(isi: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(isi.decode("utf-8-sig"))))


def test_csv_hari_kepala_indonesia_dan_angka_sama_dengan_layar(layanan):
    _, isi = _csv(layanan, "hari")
    baris = _baris(isi)

    assert baris[0] == ["Tanggal kerja", "Janjang", "Ripe", "Unripe", "JK", "TP", "Tanpa kelas",
                        "ACC", "REJ", "Rasio Ripe (%)", "Truk", "Neto (kg)"]
    assert baris[1] == ["2026-09-25", "2", "1", "0", "1", "1", "0", "1", "1", "50", "1", "7000"]
    # Hari tanpa tiket: neto kosong, bukan 0.
    assert baris[2][-1] == ""


def test_csv_kepala_inggris(layanan):
    _, isi = _csv(layanan, "truk", bahasa="en")

    assert _baris(isi)[0][:4] == ["Work date", "Plate", "Supplier", "Source"]


def test_csv_truk_menetralkan_nama_supplier_yang_mirip_rumus(layanan):
    _, isi = _csv(layanan, "truk")
    baris = _baris(isi)

    assert baris[1][1] == "BE 1234 AB"
    assert baris[1][2] == "'=HYPERLINK(\"x\")"


def test_csv_janjang_jam_pabrik_bukan_utc(layanan):
    _, isi = _csv(layanan, "janjang")
    baris = _baris(isi)

    kepala = baris[0]
    e1 = next(b for b in baris[1:] if b[kepala.index("Event ID")] == "e1")
    assert e1[kepala.index("Waktu")] == "2026-09-26 00:30:00"
    assert e1[kepala.index("Kelas")] == "Ripe"
    assert e1[kepala.index("TP")] == "ya"
    e2 = next(b for b in baris[1:] if b[kepala.index("Event ID")] == "e2")
    assert (e2[kepala.index("Kelas")], e2[kepala.index("Hasil")], e2[kepala.index("Jenis")]) == (
        "JK", "REJ", "manual")


def test_csv_janjang_ikut_saringan_hasil_dan_tidak_terpotong_halaman(layanan):
    _, semua = _csv(layanan, "janjang")
    _, jk = _csv(layanan, "janjang", hasil="jk")

    assert len(_baris(semua)) == 1 + 3
    assert len(_baris(jk)) == 1 + 1
