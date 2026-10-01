"""Timbang isi memasang truk ke line; timbang kosong melepas dan memasang truk berikutnya.

Satu truk di line sampai selesai (keputusan user 2026-10-01). Yang dikunci: truk
berikutnya tidak pernah merebut line dari truk yang masih disortir, line yang mati tidak
menggagalkan timbangan, dan truk yang sudah disortir tidak ditugaskan lagi.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import (
    BUKAN_ANTREAN,
    LINE_SEMUA_TERPAKAI,
    LINE_TIDAK_MENJAWAB,
    PENUGASAN_TANPA_LINE,
    InvalidInput,
)
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

LINES = ["line-1", "line-2", "line-3"]
PLAT = ("BE 1 AA", "BE 2 BB", "BE 3 CC")

# Jam sekarang, bukan tanggal tertulis: tes yang cuma lulus pada satu tanggal tidak
# menguji apa pun keesokan harinya.
AWAL = datetime.now(ZoneInfo("Asia/Jakarta")).replace(microsecond=0)


def _jam(menit: int = 0) -> str:
    return (AWAL + timedelta(minutes=menit)).isoformat()


class FakeLine:
    """Tiap perintah memberi giliran ke coroutine lain, seperti panggilan HTTP sungguhan,
    supaya tes balapan bisa menyelip di antaranya."""

    def __init__(self, jejak: list[tuple] | None = None) -> None:
        self.mati: set[str] = set()
        self.jejak: list[tuple] = [] if jejak is None else jejak
        # Dijalankan sekali saat line itu sedang dipanggil (operator bertindak di sela-selanya).
        self.selagi: dict[str, Callable[[], None]] = {}
        # Pelepasan line ini menunggu sampai gerbangnya dibuka (line yang lambat menjawab).
        self.lambat: dict[str, asyncio.Event] = {}

    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None):
        await asyncio.sleep(0)
        if not truck_id and (gerbang := self.lambat.pop(line.line_code, None)):
            await gerbang.wait()
        if aksi := self.selagi.pop(line.line_code, None):
            aksi()
        if line.line_code in self.mati:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, f"{line.line_code} tidak menjawab")
        self.jejak.append(("line", line.line_code, truck_id))


class FakeErp:
    def __init__(self, jejak: list[tuple]) -> None:
        self.jejak = jejak

    def visit(self, weighing_id, *, tz):
        self.jejak.append(("erp", weighing_id))


def _buat(tmp_path, line: FakeLine, erp: FakeErp | None = None) -> ConsoleService:
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), line, erp_queue=erp)


@pytest.fixture
def service(tmp_path):
    return _buat(tmp_path, FakeLine())


def _nyalakan(service, lines=LINES):
    service.simpan_penugasan_otomatis(True, lines, diubah_oleh="support@pks.test")


def _isi(service, plat, menit=0):
    return asyncio.run(service.record_weighing({"plate_number": plat, "gross_kg": 14000, "entered_at": _jam(menit)}))


def _kosong(service, plat, menit=0):
    return asyncio.run(service.record_weighing({
        "plate_number": plat, "entered_at": _jam(menit), "tare_kg": 6000, "exited_at": _jam(menit + 60),
    }))


def _plat_di_line(service) -> set[str]:
    """Plates on any line. `record_weighing` stores the id derived from the plate even
    when no truck row exists, so the ids are mapped back to the test plates."""
    terbalik = {truck_id_for(p): p for p in PLAT}
    return {terbalik.get(a["truck_id"]) for a in service.store.assignments().values() if a.get("truck_id")}


def test_otomatis_mati_tidak_memasang_apa_pun(service):
    row = _isi(service, "BE 1 AA")
    assert row["dipasang"] == []
    assert _plat_di_line(service) == set()


def test_timbang_isi_memasang_truk_ke_semua_line_pilihan(service):
    _nyalakan(service)
    row = _isi(service, "BE 1 AA")
    assert [d["line_code"] for d in row["dipasang"] if d["terpasang"]] == LINES
    assert _plat_di_line(service) == {"BE 1 AA"}


def test_cuma_line_yang_dipilih(service):
    _nyalakan(service, ["line-1", "line-3"])
    _isi(service, "BE 1 AA")
    truk_a = truck_id_for("BE 1 AA")
    pegangan = {kode: (a or {}).get("truck_id") for kode, a in service.store.assignments().items()}
    assert (pegangan.get("line-1"), pegangan.get("line-2"), pegangan.get("line-3")) == (truk_a, None, truk_a)


def test_truk_berikutnya_menunggu_selama_truk_sebelumnya_belum_timbang_kosong(service):
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    row = _isi(service, "BE 2 BB", 10)
    assert row["dipasang"] == []
    assert _plat_di_line(service) == {"BE 1 AA"}
    assert [a["plate_number"] for a in service.antrean_bongkar()] == ["BE 2 BB"]


def test_timbang_kosong_melepas_lalu_memasang_truk_berikutnya(service):
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 10)
    row = _kosong(service, "BE 1 AA")
    assert {d["plate_number"] for d in row["dipasang"]} == {"BE 2 BB"}
    assert _plat_di_line(service) == {"BE 2 BB"}
    assert service.antrean_bongkar() == []


def test_urutan_antrean_mengikuti_timbang_isi(service):
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 10)
    _isi(service, "BE 3 CC", 20)
    _kosong(service, "BE 1 AA")
    assert _plat_di_line(service) == {"BE 2 BB"}
    assert [a["plate_number"] for a in service.antrean_bongkar()] == ["BE 3 CC"]


def test_lepas_manual_semua_line_memasang_truk_berikutnya(service):
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 10)
    hasil = [asyncio.run(service.release_truck_by_operator(kode)) for kode in LINES]
    assert hasil[0]["dipasang"] == [] and hasil[1]["dipasang"] == []
    assert {d["plate_number"] for d in hasil[2]["dipasang"]} == {"BE 2 BB"}
    assert _plat_di_line(service) == {"BE 2 BB"}


def test_truk_yang_sudah_disortir_tidak_ditugaskan_lagi(service):
    """Dilepas manual sebelum timbang kosong: tiketnya masih terbuka, tapi sudah pernah di line."""
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    for kode in LINES:
        asyncio.run(service.release_truck_by_operator(kode))
    assert _plat_di_line(service) == set()
    assert service.antrean_bongkar() == []


def test_truk_yang_tertimbang_isi_dua_kali_tidak_naik_lagi_sesudah_pergi(service):
    """Timbang isi kedua karena salah meninggalkan tiket lama yang terbuka. Sesudah truk itu
    timbang kosong di tiket barunya, tiket lama itu tidak boleh memasangnya lagi ke line."""
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    _isi(service, "BE 1 AA", 1)
    _isi(service, "BE 2 BB", 10)
    row = _kosong(service, "BE 1 AA", 1)
    assert {d["plate_number"] for d in row["dipasang"]} == {"BE 2 BB"}
    assert _plat_di_line(service) == {"BE 2 BB"}
    assert service.antrean_bongkar() == []
    for kode in LINES:
        asyncio.run(service.release_truck_by_operator(kode))
    assert _plat_di_line(service) == set()


def _timbang_isi_selagi_timbang_kosong(service, aksi):
    """A di line, B menunggu; timbang kosong A tertahan di pelepasan line-2, dan selama itu
    `aksi()` jalan (timbang isi truk lain, atau tombol). Mengembalikan (hasil aksi, hasil timbang kosong)."""
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 5)

    async def jalankan():
        gerbang = asyncio.Event()
        service.line_client.lambat["line-2"] = gerbang
        keluar = asyncio.create_task(service.record_weighing({
            "plate_number": "BE 1 AA", "entered_at": _jam(0), "tare_kg": 6000, "exited_at": _jam(60),
        }))
        for _ in range(5):
            await asyncio.sleep(0)
        try:
            hasil = await aksi()
        except InvalidInput as exc:
            hasil = exc
        gerbang.set()
        return hasil, await keluar

    return asyncio.run(jalankan())


def test_timbang_isi_selagi_truk_lain_timbang_kosong_menunggu(service):
    """Taranya sudah tertulis, tapi line-2 dan line-3 masih memegang A: A masih disortir.
    Truk berikutnya naik ke SEMUA line sesudah A selesai dilepas, bukan ke sebagian (D9)."""
    truk_b = truck_id_for("BE 2 BB")

    async def timbang_isi_c():
        return await service.record_weighing({"plate_number": "BE 3 CC", "gross_kg": 14000, "entered_at": _jam(10)})

    row_c, row_keluar = _timbang_isi_selagi_timbang_kosong(service, timbang_isi_c)
    assert row_c["dipasang"] == []
    assert [d["line_code"] for d in row_keluar["dipasang"] if d["plate_number"] == "BE 2 BB"] == LINES
    assert {kode: a["truck_id"] for kode, a in service.store.assignments().items()} == dict.fromkeys(LINES, truk_b)
    assert [a["plate_number"] for a in service.antrean_bongkar()] == ["BE 3 CC"]


def test_tugaskan_sekarang_selagi_timbang_kosong_ditolak(service):
    """Tombolnya juga tidak memasang truk ke sebagian line selama truk sebelumnya dilepas."""
    async def tugaskan_b():
        return await service.pasang_dari_antrean(service.antrean_bongkar()[0]["weighing_id"])

    galat, row_keluar = _timbang_isi_selagi_timbang_kosong(service, tugaskan_b)
    assert isinstance(galat, InvalidInput) and galat.code == LINE_SEMUA_TERPAKAI
    assert [d["line_code"] for d in row_keluar["dipasang"]] == LINES
    assert _plat_di_line(service) == {"BE 2 BB"}


def test_tiket_ganda_dengan_jam_terbalik_tidak_memasang_truk_lagi(service):
    """Tiket ganda yang jam timbang isinya (entered_at) dan jam terimanya (received_at)
    berlawanan urutan: pelepasan menaut tiket dengan entered_at terbaru, jadi antrean
    memakai urutan yang sama dan tiket lainnya tidak pernah ditawarkan."""
    _nyalakan(service)
    _isi(service, "BE 1 AA", 5)
    _isi(service, "BE 1 AA", 0)
    _isi(service, "BE 2 BB", 10)
    row = _kosong(service, "BE 1 AA", 5)
    assert {d["plate_number"] for d in row["dipasang"]} == {"BE 2 BB"}
    assert _plat_di_line(service) == {"BE 2 BB"}
    assert service.antrean_bongkar() == []


def test_truk_yang_sedang_dilepas_tidak_pernah_muncul_di_antrean(service):
    """Lepas mengosongkan line lalu menautkan tiketnya tanpa `await` di antaranya: tidak
    ada saat truk itu sudah tidak di line tapi belum tertaut, jadi coroutine lain (poll,
    penugasan otomatis) tidak pernah melihatnya sebagai truk yang menunggu."""
    _nyalakan(service, ["line-1"])
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 10)
    terlihat: list[list[str]] = []

    async def jalankan():
        selesai = asyncio.Event()

        async def intip():
            while not selesai.is_set():
                terlihat.append([a["plate_number"] for a in service.antrean_bongkar()])
                await asyncio.sleep(0)

        async def lepas():
            try:
                return await service.release_truck_by_operator("line-1")
            finally:
                selesai.set()

        return (await asyncio.gather(intip(), lepas()))[1]

    hasil = asyncio.run(jalankan())
    assert len(terlihat) > 1, "intip harus menyelip di sela perintah ke line"
    assert all("BE 1 AA" not in antre for antre in terlihat)
    assert [d["plate_number"] for d in hasil["dipasang"]] == ["BE 2 BB"]
    assert _plat_di_line(service) == {"BE 2 BB"}


def test_dua_timbang_isi_bersamaan_cuma_satu_truk_di_line(service):
    """Tanpa kunci, timbang isi kedua melihat line masih bebas (truk pertama belum
    tercatat selama line menjawab) dan memasang truk pertama sekali lagi."""
    _nyalakan(service)

    async def bersamaan():
        return await asyncio.gather(*(
            service.record_weighing({"plate_number": plat, "gross_kg": 14000, "entered_at": _jam(menit)})
            for plat, menit in (("BE 1 AA", 0), ("BE 2 BB", 1))
        ))

    row_a, row_b = asyncio.run(bersamaan())
    truk_a = truck_id_for("BE 1 AA")
    assert [d["line_code"] for d in row_a["dipasang"] if d["terpasang"]] == LINES
    assert row_b["dipasang"] == []
    assert service.line_client.jejak == [("line", kode, truk_a) for kode in LINES]
    assert [a["plate_number"] for a in service.antrean_bongkar()] == ["BE 2 BB"]


def test_line_yang_diisi_operator_selagi_memasang_tidak_ditimpa(service):
    """Line-2 lambat menjawab, operator menugaskan truk lain ke line-3 lewat dropdown
    di sela-selanya: truk itu tidak boleh terdorong keluar oleh penugasan otomatis."""
    _nyalakan(service)
    truk_c = truck_id_for("BE 3 CC")
    service.line_client.selagi["line-2"] = lambda: service.store.set_assignment("line-3", "manual-c", truk_c)
    row = _isi(service, "BE 1 AA")
    assert [d["line_code"] for d in row["dipasang"]] == ["line-1", "line-2"]
    assert service.store.assignments()["line-3"]["truck_id"] == truk_c


def test_line_mati_tidak_menggagalkan_timbangan(service):
    _nyalakan(service)
    service.line_client.mati.add("line-2")
    row = _isi(service, "BE 1 AA")
    assert row["gross_kg"] == 14000
    assert {d["line_code"]: d["terpasang"] for d in row["dipasang"]} == {
        "line-1": True, "line-2": False, "line-3": True,
    }


def test_galat_penugasan_tidak_menggagalkan_timbangan(service, monkeypatch):
    """Penugasan jalan di jalur uang: apa pun yang rusak di sana, beratnya tetap tersimpan."""
    _nyalakan(service)

    def rusak(_sejak):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(service.store, "unloading_queue", rusak)
    row = _isi(service, "BE 1 AA")
    assert row["gross_kg"] == 14000 and row["dipasang"] == []
    assert service.store.weighing(row["id"])["gross_kg"] == 14000


def test_kunjungan_diantre_utuh_sebelum_truk_berikutnya_dipasang(tmp_path):
    """Timbang kosong: semua line dilepas, kunjungannya diantre SEKALI, baru truk
    berikutnya naik. Pesan yang diantre di tengah membawa tara dengan sebagian line."""
    jejak: list[tuple] = []
    service = _buat(tmp_path, FakeLine(jejak), FakeErp(jejak))
    _nyalakan(service)
    tiket_a = _isi(service, "BE 1 AA")["id"]
    _isi(service, "BE 2 BB", 10)
    jejak.clear()
    _kosong(service, "BE 1 AA")
    truk_b = truck_id_for("BE 2 BB")
    assert sorted(jejak[:3]) == [("line", kode, "") for kode in LINES]
    assert jejak[3:] == [("erp", tiket_a)] + [("line", kode, truk_b) for kode in LINES]


def test_tugaskan_sekarang_melompati_urutan(service):
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 10)
    wid_b = next(a["weighing_id"] for a in service.antrean_bongkar() if a["plate_number"] == "BE 2 BB")
    dipasang = asyncio.run(service.pasang_dari_antrean(wid_b))
    assert all(d["terpasang"] for d in dipasang) and len(dipasang) == 3
    assert _plat_di_line(service) == {"BE 2 BB"}
    assert [a["plate_number"] for a in service.antrean_bongkar()] == ["BE 1 AA"]


def test_tugaskan_sekarang_tanpa_line_bebas_ditolak(service):
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 10)
    wid_b = service.antrean_bongkar()[0]["weighing_id"]
    with pytest.raises(InvalidInput) as galat:
        asyncio.run(service.pasang_dari_antrean(wid_b))
    assert galat.value.code == LINE_SEMUA_TERPAKAI


def test_tugaskan_sekarang_tanpa_line_terpilih_ditolak(service):
    """Bukan "semua line terpakai": tidak ada line yang dipilih di Setelan."""
    service.simpan_penugasan_otomatis(False, [], diubah_oleh="support@pks.test")
    _isi(service, "BE 1 AA")
    with pytest.raises(InvalidInput) as galat:
        asyncio.run(service.pasang_dari_antrean(service.antrean_bongkar()[0]["weighing_id"]))
    assert galat.value.code == PENUGASAN_TANPA_LINE
    assert _plat_di_line(service) == set()


def test_tugaskan_sekarang_tiket_di_luar_antrean_ditolak(service):
    with pytest.raises(InvalidInput) as galat:
        asyncio.run(service.pasang_dari_antrean("tidak-ada"))
    assert galat.value.code == BUKAN_ANTREAN


def test_lewati_lalu_tidak_ditugaskan_otomatis(service):
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 10)
    service.lewati_antrean(service.antrean_bongkar()[0]["weighing_id"], oleh="op@pks.test")
    row = _kosong(service, "BE 1 AA")
    assert row["dipasang"] == []
    assert _plat_di_line(service) == set()


def test_lewati_dua_kali_ditolak(service):
    _isi(service, "BE 1 AA")
    wid = service.antrean_bongkar()[0]["weighing_id"]
    service.lewati_antrean(wid, oleh="op@pks.test")
    with pytest.raises(InvalidInput) as galat:
        service.lewati_antrean(wid, oleh="op@pks.test")
    assert galat.value.code == BUKAN_ANTREAN


def test_lewati_truk_yang_sudah_di_line_ditolak(service):
    """Layar yang tertinggal satu poll masih menampilkan truk yang barusan naik ke line:
    Lewati-nya ditolak, bukan diam diam menandai tiket yang sedang disortir."""
    _nyalakan(service)
    wid_a = _isi(service, "BE 1 AA")["id"]
    with pytest.raises(InvalidInput) as galat:
        service.lewati_antrean(wid_a, oleh="op@pks.test")
    assert galat.value.code == BUKAN_ANTREAN
    assert service.store.weighing(wid_a)["unloading_queue_skipped_at"] is None


def test_setelan_tersimpan_dan_terbaca(service):
    assert service.penugasan_otomatis()["aktif"] is False
    _nyalakan(service, ["line-2"])
    s = service.penugasan_otomatis()
    assert (s["aktif"], s["lines"]) == (True, ["line-2"])
    assert [ln["line_code"] for ln in s["lines_tersedia"]] == LINES


def test_state_membawa_antrean_dan_setelan(service):
    _isi(service, "BE 1 AA")
    s = service.state()
    assert [a["plate_number"] for a in s["antrean_bongkar"]] == ["BE 1 AA"]
    assert s["penugasan_otomatis"] == {"aktif": False, "lines": LINES}
