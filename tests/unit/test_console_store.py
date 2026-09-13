"""Console SQLite index + ingest path (plan §6.2).

The console may never scan directories; everything the operator screen reads
comes from this index. What is pinned here: event idempotency (a line retries
after the console was down), grouping by `tanggal_kerja` rather than by receive
time, truck assignments that survive a restart, and Sumber TBS staying 3 values.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.ffb_source import label_sumber
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

WIB = ZoneInfo("Asia/Jakarta")


class FakeLineClient:
    """Stands in for LineClient. The seam is a collaborator, not a private method."""

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
    # A line's OutboxRetryWorker resends until it gets a 2xx. Without dedupe one
    # bunch can be counted over and over on the operator screen.
    service.ingest(_event(service))
    service.ingest(_event(service))
    assert service.store.summary("2026-09-10")[0]["total"] == 1


def test_payload_cacat_ditolak(service):
    with pytest.raises(ValueError):
        service.ingest(_event(service, timestamp=""))
    with pytest.raises(ValueError):
        service.ingest(_event(service, machine_id=""))


def test_machine_tak_dikenal_tetap_tersimpan_dan_kelihatan(service):
    # An event whose machine_id is not in the registry must NOT be swallowed:
    # a mistyped LINE_N_MACHINE_ID has to be visible on the screen.
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
    # Plan §6.4: an in-memory assignment is lost when the console restarts
    # mid-unload, and the operator has to retype the truck already on the belt.
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
    # The edge NEVER decides sumber (plan §3.5b), it only maps it to a label.
    # The raw value must stay stored as 3 values or the cloud's Plasma vs Pihak
    # Ketiga reporting cannot be reconstructed.
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
    # If the line does not answer but the screen still shows a truck attached,
    # the operator thinks it is done and the next bunches count with no truck.
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
    # Env may only enter through Settings. If LINE_N_MACHINE_ID stops being
    # read, every event from that line falls into the "unknown line" branch
    # without raising.
    monkeypatch.setenv("LINE_2_MACHINE_ID", "  mesin-dua  ")
    service = _service(tmp_path)
    assert service.lines[1].machine_id == "mesin-dua"
    service.ingest(_event(service, machine_id="mesin-dua", timestamp="2026-09-09T18:30:00+00:00"))
    assert {r["line_code"] for r in service.store.summary("2026-09-10")} == {"line-2"}


def test_rekap_per_truk_menjumlah_neto_bukan_mengalikan_janjang(service):
    # Two tickets for one truck in a day. Joined in SQL that would double every
    # bunch; the recap must show 3 bunches and both netos added up.
    truk = service.daftar_truk_manual("B 1234 XY")["id"]
    for i, hasil in enumerate(("ACC", "ACC", "REJ")):
        service.ingest(_event(service, event_id=f"ev-{i}", truck_id=truk, ripeness_status=hasil))
    for ref, bruto in (("TKT-1", 12000), ("TKT-2", 11000)):
        service.catat_timbangan({
            "ref": ref, "plate_number": "B 1234 XY",
            "waktu_masuk": "2026-09-09T18:30:00+00:00",
            "bruto_kg": bruto, "tara_kg": 5000,
        })

    (baris,) = service.rekap("2026-09-10")
    assert (baris["total"], baris["acc"], baris["rej"]) == (3, 2, 1)
    assert baris["neto_kg"] == 13000  # (12000-5000) + (11000-5000)
    assert baris["plate_number"] == "B 1234 XY"


def test_rekap_tetap_menampilkan_janjang_tanpa_truk(service):
    # A line graded before anyone assigned a truck. Dropping the row would hide
    # exactly the thing the operator needs to notice.
    service.ingest(_event(service))
    (baris,) = service.rekap("2026-09-10")
    assert baris["truck_id"] is None and baris["total"] == 1
    assert baris["neto_kg"] is None
