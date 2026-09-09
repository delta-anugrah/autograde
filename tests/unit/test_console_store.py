"""Index SQLite konsol + jalur ingest (§6.2 rencana PalmOS).

Konsol tidak boleh memindai direktori; semua yang dibaca layar operator datang
dari index ini. Yang dikunci di sini: idempotensi event (line retry setelah
konsol mati), pengelompokan per `tanggal_kerja` (bukan per waktu terima),
penugasan truk yang selamat dari restart, dan Sumber TBS yang tetap 3 nilai.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.sumber_tbs import label_sumber
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import MASTER_CURSOR_KEY, ConsoleService
from palmgrade.workers.master_data_worker import MasterDataWorker

WIB = ZoneInfo("Asia/Jakarta")


class FakeLineClient:
    """Pengganti LineClient. Seam-nya kolaborator, bukan method privat service."""

    def __init__(self, *, mati: bool = False) -> None:
        self.mati = mati
        self.dipanggil: list[tuple[str, str]] = []

    async def assign_truck(self, line: LineEndpoint, **_kw) -> None:
        self._catat(line, "assign")

    async def manual_reject(self, line: LineEndpoint, **_kw) -> None:
        self._catat(line, "reject")

    def _catat(self, line: LineEndpoint, aksi: str) -> None:
        if self.mati:
            raise LineUnavailable(f"{line.line_code} tidak menjawab")
        self.dipanggil.append((line.line_code, aksi))


def _service(tmp_path, line_client: FakeLineClient | None = None) -> ConsoleService:
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    store = ConsoleStore(tmp_path / "console.db")
    return ConsoleService(settings, store, line_client or FakeLineClient())


@pytest.fixture
def service(tmp_path):
    return _service(tmp_path)


def _event(service, **over):
    payload = {
        "event_id": "ev-1",
        "machine_id": service.lines[0].machine_id,
        "timestamp": "2026-09-09T18:30:00+00:00",  # = 2026-09-10 01:30 WIB
        "ripeness_status": "ACC",
        "ripeness_confidence": 0.91,
        "capture_type": "auto",
        "image_path": "captures/results/2026-09-09/f.webp",
        "truck_id": None,
        "assignment_id": None,
    }
    payload.update(over)
    return payload


def test_ingest_menyimpan_tanggal_kerja_wib_bukan_tanggal_terima(service):
    assert service.ingest(_event(service)) == "2026-09-10"
    assert service.store.summary("2026-09-10")[0]["total"] == 1
    assert service.store.summary("2026-09-09") == []


def test_event_yang_sama_dikirim_ulang_tidak_dihitung_dua_kali(service):
    # OutboxRetryWorker line mengirim ulang sampai dapat 2xx. Tanpa dedupe,
    # satu tandan bisa terhitung berkali-kali di layar operator.
    service.ingest(_event(service))
    service.ingest(_event(service))
    assert service.store.summary("2026-09-10")[0]["total"] == 1


def test_payload_cacat_ditolak(service):
    with pytest.raises(ValueError):
        service.ingest(_event(service, timestamp=""))
    with pytest.raises(ValueError):
        service.ingest(_event(service, machine_id=""))


def test_machine_tak_dikenal_tetap_tersimpan_dan_kelihatan(service):
    # Event dari machine_id yang tidak cocok registry TIDAK boleh ditelan diam-
    # diam: LINE_N_MACHINE_ID yang salah ketik harus kelihatan di layar.
    sekarang = datetime.now(WIB).isoformat()
    service.ingest(_event(service, machine_id="entah-siapa", timestamp=sekarang))
    state = service.state()
    asing = [ln for ln in state["lines"] if ln["line_code"] == "entah-siapa"]
    assert asing and asing[0]["total"] == 1
    assert [ln["line_code"] for ln in state["lines"]][:3] == ["line-1", "line-2", "line-3"]


def test_summary_memisahkan_acc_dan_rej_per_line(service):
    service.ingest(_event(service, event_id="a"))
    service.ingest(_event(service, event_id="b", ripeness_status="REJ"))
    service.ingest(_event(service, event_id="c", machine_id=service.lines[1].machine_id))
    per_line = {r["line_code"]: r for r in service.store.summary("2026-09-10")}
    assert (per_line["line-1"]["acc"], per_line["line-1"]["rej"]) == (1, 1)
    assert per_line["line-2"]["total"] == 1


def test_penugasan_truk_selamat_dari_restart_konsol(tmp_path):
    # §6.4: penugasan di memori hilang saat konsol restart di tengah bongkar
    # muat, dan operator harus mengetik ulang truk yang sedang di belt.
    ConsoleStore(tmp_path / "console.db").set_assignment("line-1", "as-1", "truk-1")
    lagi = _service(tmp_path)
    assert lagi.store.assignments()["line-1"]["assignment_id"] == "as-1"


def test_url_gambar_menyuntikkan_folder_line(service):
    service.ingest(_event(service))
    row = service.history("2026-09-10")[0]
    assert row["image_url"] == "/captures/line-1/results/2026-09-09/f.webp"


def test_url_r2_absolut_diteruskan_apa_adanya(service):
    service.ingest(_event(service, image_path="https://captures.smagri.id/x/f.webp"))
    assert service.history("2026-09-10")[0]["image_url"] == "https://captures.smagri.id/x/f.webp"


def test_sumber_tbs_hanya_label_tampilan_dan_tetap_tiga_nilai(service, tmp_path):
    # Edge TIDAK PERNAH menentukan sumber (§3.5b) — cuma memetakan ke label.
    # Nilai mentahnya wajib tetap tersimpan 3 nilai supaya laporan Plasma vs
    # Pihak Ketiga di cloud tidak hilang.
    assert label_sumber("Inti") == "Internal"
    assert label_sumber("Plasma") == label_sumber("Pihak Ketiga") == "External"
    assert label_sumber(None) is None

    service.store.upsert_supplier({"id": "s1", "name": "KUD A", "sumber": "Plasma", "status": "active"})
    service.store.upsert_truck({"id": "t1", "plate_number": "BE 1234 XX", "supplier_id": "s1", "status": "active"})
    truk = service.trucks()[0]
    assert truk["sumber_label"] == "External"
    assert "sumber" not in truk
    disk = sqlite3.connect(tmp_path / "console.db")
    assert disk.execute("SELECT sumber FROM suppliers WHERE id='s1'").fetchone()[0] == "Plasma"
    disk.close()


def test_master_data_dari_cloud_selalu_menang(service):
    service.store.upsert_supplier({"id": "s1", "name": "Lama", "sumber": "Inti", "status": "active"})
    service.store.upsert_supplier({"id": "s1", "name": "Baru", "sumber": "Pihak Ketiga", "status": "active"})
    service.store.upsert_truck({"id": "t1", "plate_number": "BE 1", "supplier_id": "s1", "status": "active"})
    truk = service.trucks()[0]
    assert (truk["supplier_name"], truk["sumber_label"]) == ("Baru", "External")


def test_penugasan_gagal_tidak_dicatat_seolah_berhasil(tmp_path):
    # Kalau line tidak menjawab tapi layar tetap menampilkan truk terpasang,
    # operator mengira sudah beres dan tandan berikutnya terhitung tanpa truk.
    service = _service(tmp_path, FakeLineClient(mati=True))
    with pytest.raises(LineUnavailable):
        asyncio.run(service.assign_truck("line-1", "t1"))
    assert service.store.assignments() == {}


def test_penugasan_berhasil_dicatat(tmp_path):
    line_client = FakeLineClient()
    service = _service(tmp_path, line_client)
    hasil = asyncio.run(service.assign_truck("line-1", "t1"))
    assert service.store.assignments()["line-1"]["assignment_id"] == hasil["assignment_id"]
    assert line_client.dipanggil == [("line-1", "assign")]


def test_machine_id_line_dibaca_dari_env_lewat_settings(monkeypatch, tmp_path):
    # Env cuma boleh masuk lewat Settings. Kalau LINE_N_MACHINE_ID berhenti
    # terbaca, semua event line itu jatuh ke cabang "line asing" tanpa error.
    monkeypatch.setenv("LINE_2_MACHINE_ID", "  mesin-dua  ")
    service = _service(tmp_path)
    assert service.lines[1].machine_id == "mesin-dua"
    service.ingest(_event(service, machine_id="mesin-dua", timestamp="2026-09-09T18:30:00+00:00"))
    assert {r["line_code"] for r in service.store.summary("2026-09-10")} == {"line-2"}


def test_kursor_master_data_tidak_maju_kalau_ada_baris_gagal(service):
    # Melewati satu baris yang tidak pernah mendarat = pabrik terjebak selamanya
    # di matriks setengah basi, termasuk pencabutan truk yang sudah dilakukan cloud.
    worker = MasterDataWorker(service.settings, service.store)
    worker.apply({"server_time": "2026-09-09T10:00:00Z",
                  "suppliers": [{"id": "s1", "name": "KUD A", "sumber": "Inti"}]})
    assert service.store.get_state(MASTER_CURSOR_KEY) == "2026-09-09T10:00:00Z"

    worker.apply({"server_time": "2026-09-09T11:00:00Z",
                  "suppliers": [{"name": "tanpa id"}]})  # KeyError saat upsert
    assert service.store.get_state(MASTER_CURSOR_KEY) == "2026-09-09T10:00:00Z"
