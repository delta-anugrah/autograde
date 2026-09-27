"""Integrasi impor grading: CSV hasil Unduh CSV di satu konsol, diimpor di konsol lain.

Tanpa tiruan di tengahnya:

- Janjang masuk konsol asal lewat `ConsoleService.ingest` (payload kontrak §5 dari
  line), truk lewat `register_manual_truck`, jadi `work_date` dan truknya dihitung
  aturan yang asli.
- CSV-nya dibuat `RiwayatService.csv` yang asli (bahasa id dan en).
- Konsol tujuan punya console.db sendiri; impornya lewat `ImporGradingService` yang
  asli, dan hasilnya dibaca `RiwayatService` yang asli di konsol tujuan.

Buktinya: angka per hari dan per truk di tujuan sama dengan di asal, dan ekspor ulang
dari tujuan identik per byte dengan ekspor dari asal. Neto tidak ikut: tiket timbangan
bukan bagian dari CSV grading.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.bahaya import MODE_TRANSAKSI
from palmgrade.domain.impor_grading import sidik
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.riwayat_repository import RiwayatStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.impor_grading_service import ImporGradingService
from palmgrade.services.riwayat_service import RiwayatService

HARI_INI = "2026-09-26"
ANGKA = ("total", "acc", "rej", "ripe", "unripe", "jk", "tp", "tanpa_kelas")


class _LineDiam:
    """Line yang tidak pernah dipanggil di test ini."""


class Konsol:
    def __init__(self, root, nama: str) -> None:
        settings = replace(Settings(), repo_root=root / nama, factory_tz="Asia/Jakarta")
        db = root / nama / "console.db"
        self.store = ConsoleStore(db)
        self.service = ConsoleService(settings, self.store, _LineDiam())
        self.riwayat = RiwayatService(RiwayatStore(db), hari_ini=lambda: HARI_INI, zona="Asia/Jakarta")
        self.impor = ImporGradingService(self.store, lines=self.service.lines, zona="Asia/Jakarta",
                                         hari_ini=lambda: HARI_INI)

    def ekspor(self, bahasa: str = "id") -> bytes:
        f = self.riwayat.filter(dari="2026-09-20", sampai=HARI_INI)
        _, isi = self.riwayat.csv(f, tampilan="janjang", bahasa=bahasa)
        return b"".join(isi)

    def impor_berkas(self, isi: bytes) -> dict:
        periksa = self.impor.periksa(isi, nama_berkas="riwayat.csv")
        assert periksa["bisa_impor"], periksa
        return self.impor.impor(isi, nama_berkas="riwayat.csv", sidik=periksa["sidik"], oleh="support@pks.id")

    def angka(self, tampilan: str) -> list[tuple]:
        f = self.riwayat.filter(dari="2026-09-20", sampai=HARI_INI)
        items = self.riwayat.halaman(f, tampilan=tampilan, limit=200, offset=0, ringkasan=False)["items"]
        kunci = ("work_date",) if tampilan == "hari" else ("work_date", "plate_number")
        # Janjang tanpa truk punya plat None; "" supaya bisa diurutkan bersama yang lain.
        return sorted(tuple(r.get(k) or "" for k in kunci) + tuple(r.get(k) for k in ANGKA) for r in items)


def _janjang(konsol: ConsoleService, nomor: int, ts: str, *, line: int = 0, status="ACC", kelas="Ripe",
             truk=None, tp=None, jenis="auto"):
    return konsol.ingest({
        "event_id": f"00000000-0000-5000-8000-{nomor:012d}", "machine_id": konsol.lines[line].machine_id,
        "timestamp": ts, "ripeness_status": status, "prediction": "Acc" if status == "ACC" else "Rej",
        "grade_class": kelas, "ripeness_confidence": 0.9, "capture_type": jenis,
        "image_path": f"captures/results/2026-09-24/{nomor}.webp", "truck_id": truk, "assignment_id": None,
        "tp_status": "PASS" if tp else None, "tp_confidence": tp,
    })


@pytest.fixture
def asal(tmp_path) -> Konsol:
    k = Konsol(tmp_path, "asal")
    truk_a = k.service.register_manual_truck("BE 1234 AB")["id"]
    truk_b = k.service.register_manual_truck("B 9 ZZ")["id"]
    _janjang(k.service, 1, "2026-09-24T01:00:00+00:00", truk=truk_a)                      # 08:00 WIB
    _janjang(k.service, 2, "2026-09-24T02:00:00+00:00", status="REJ", kelas="JK", truk=truk_a)
    _janjang(k.service, 3, "2026-09-24T03:00:00+00:00", line=1, truk=truk_b, tp=0.95)
    _janjang(k.service, 4, "2026-09-24T18:30:00+00:00", status="REJ", kelas="Unripe", truk=truk_b)  # 01:30 tgl 25
    _janjang(k.service, 5, "2026-09-25T04:00:00+00:00", status="REJ", kelas=None, jenis="manual")
    _janjang(k.service, 6, "2026-09-26T02:00:00+00:00", truk=truk_a)                      # hari ini
    # Buah bertumpuk: line memaksa REJ tapi kelasnya tetap Ripe. Ada tiap hari sibuk.
    _janjang(k.service, 7, "2026-09-24T04:00:00+00:00", status="REJ", kelas="Ripe", truk=truk_a)
    asyncio.run(k.service.record_weighing({
        "plate_number": "BE 1234 AB", "gross_kg": 12000, "tare_kg": 4500, "entered_at": "2026-09-24T08:00:00+07:00",
    }))
    return k


@pytest.mark.parametrize("bahasa", ["id", "en"])
def test_impor_ke_konsol_lain_memberi_angka_riwayat_yang_sama(tmp_path, asal, bahasa):
    tujuan = Konsol(tmp_path, f"tujuan-{bahasa}")

    batch = tujuan.impor_berkas(asal.ekspor(bahasa))

    assert (batch["added"], batch["skipped_today"], batch["new_trucks"]) == (6, 1, 2)
    kemarin_saja = [r for r in asal.angka("hari") if r[0] != HARI_INI]
    assert tujuan.angka("hari") == kemarin_saja
    assert tujuan.angka("truk") == [r for r in asal.angka("truk") if r[0] != HARI_INI]


def test_ekspor_ulang_dari_konsol_tujuan_identik_per_byte(tmp_path, asal):
    """Satu-satunya perbedaan yang boleh: janjang hari ini, yang memang tidak diimpor."""
    tujuan = Konsol(tmp_path, "tujuan")
    asli = asal.ekspor()

    tujuan.impor_berkas(asli)

    tanpa_hari_ini = b"\r\n".join(b for b in asli.split(b"\r\n") if not b.startswith(HARI_INI.encode()))
    assert tujuan.ekspor() == tanpa_hari_ini


def test_pulihkan_sesudah_danger_zone_di_pc_yang_sama_lalu_batalkan(asal):
    """Ekspor dulu, hapus transaksi, impor kembali: data hari-hari sebelumnya pulih.
    Batal mengembalikan keadaan sesudah penghapusan."""
    sebelum = [r for r in asal.angka("hari") if r[0] != HARI_INI]
    berkas = asal.ekspor()
    asal.store.hapus_data(MODE_TRANSAKSI)

    batch = asal.impor_berkas(berkas)
    pulih = asal.angka("hari")
    asal.impor.batalkan(batch["id"], oleh="support@pks.id")

    assert pulih == sebelum
    assert asal.angka("hari") == []


def test_impor_kedua_berkas_yang_sama_tidak_menggandakan(tmp_path, asal):
    tujuan = Konsol(tmp_path, "tujuan")
    berkas = asal.ekspor()
    tujuan.impor_berkas(berkas)

    periksa = tujuan.impor.periksa(berkas, nama_berkas="lagi.csv")

    assert (periksa["baru"], periksa["sudah_ada"], periksa["bisa_impor"]) == (0, 6, False)
    assert periksa["sidik"] == sidik(berkas)
