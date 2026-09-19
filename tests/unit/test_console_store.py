"""Console SQLite index + ingest path (plan §6.2).

The console may never scan directories; everything the operator screen reads
comes from this index. What is pinned here: event idempotency (a line retries
after the console was down), grouping by `work_date` rather than by receive
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
from palmgrade.domain.operator_error import (
    DI_BAWAH_MINIMUM,
    LINE_TIDAK_MENJAWAB,
    OperatorError,
)
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
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, f"{line.line_code} tidak menjawab")
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


def test_ingest_menyimpan_work_date_wib_bukan_tanggal_terima(service):
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


def test_source_label_mirrors_autoerp_and_the_raw_group_stays_stored(service, tmp_path):
    # The edge never decides the source (§3.5b); it mirrors AutoERP's
    # `sumber_for_supplier`. Plasma vs agent lives on the supplier group, so
    # that value stays stored as it arrived.
    service.store.upsert_supplier(
        {"id": "s1", "name": "KUD A", "source_group": "Plasma", "status": "active"}
    )
    service.store.upsert_truck({"id": "t1", "plate_number": "BE 1 AA", "supplier_id": "s1", "status": "active"})
    service.store.upsert_truck({"id": "t2", "plate_number": "BE 2 BB", "status": "active", "erp_name": "BE 2 BB"})
    service.store.upsert_truck({"id": "t3", "plate_number": "BE 3 CC", "status": "manual"})

    trucks = service.trucks()
    assert {t["plate_number"]: t["source_label"] for t in trucks} == {
        "BE 1 AA": "External",
        "BE 2 BB": "Internal",
        "BE 3 CC": None,
    }
    assert not {"source_group", "has_supplier", "in_erp"} & set(trucks[0])
    disk = sqlite3.connect(tmp_path / "console.db")
    assert disk.execute("SELECT source_group FROM suppliers WHERE id='s1'").fetchone()[0] == "Plasma"
    disk.close()


def test_every_console_view_labels_the_source_the_same_way(service):
    # One rule, five queries. A view still reading the supplier group would
    # show another source for the same truck on a different tab.
    service.store.upsert_truck({"id": "t2", "plate_number": "BE 2 BB", "status": "active", "erp_name": "BE 2 BB"})
    today = service.today()
    service.store.set_assignment("line-1", "as-1", "t2")
    service.ingest(_event(service, truck_id="t2", timestamp=datetime.now(WIB).isoformat()))
    service.store.upsert_weighing({
        "id": "w1", "ref": "r1", "plate_number": "BE 2 BB", "plate_norm": "BE2BB", "truck_id": "t2",
        "work_date": today, "gross_kg": 15000.0, "tare_kg": 5000.0, "net_kg": 10000.0,
        "entered_at": None, "exited_at": None,
    })

    state = service.state()
    labels = [
        state["lines"][0]["assignment"]["source_label"],
        state["recent"][0]["source_label"],
        service.recap(today)[0]["source_label"],
        service.weighings(today)[0]["source_label"],
    ]
    assert labels == ["Internal"] * 4


def test_master_data_dari_cloud_selalu_menang(service):
    service.store.upsert_supplier(
        {"id": "s1", "name": "Lama", "source_group": "Inti", "status": "active"}
    )
    service.store.upsert_supplier(
        {"id": "s1", "name": "Baru", "source_group": "Pihak Ketiga", "status": "active"}
    )
    service.store.upsert_truck({"id": "t1", "plate_number": "BE 1", "supplier_id": "s1", "status": "active"})
    truk = service.trucks()[0]
    assert (truk["supplier_name"], truk["source_label"]) == ("Baru", "External")


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
    truk = service.register_manual_truck("B 1234 XY")["id"]
    for i, hasil in enumerate(("ACC", "ACC", "REJ")):
        service.ingest(_event(service, event_id=f"ev-{i}", truck_id=truk, ripeness_status=hasil))
    for ref, bruto in (("TKT-1", 12000), ("TKT-2", 11000)):
        service.record_weighing({
            "ref": ref, "plate_number": "B 1234 XY",
            "entered_at": "2026-09-09T18:30:00+00:00",
            "gross_kg": bruto, "tare_kg": 5000,
        })

    (baris,) = service.recap("2026-09-10")
    assert (baris["total"], baris["acc"], baris["rej"]) == (3, 2, 1)
    assert baris["net_kg"] == 13000  # (12000-5000) + (11000-5000)
    assert baris["plate_number"] == "B 1234 XY"


def test_rekap_tetap_menampilkan_janjang_tanpa_truk(service):
    # A line graded before anyone assigned a truck. Dropping the row would hide
    # exactly the thing the operator needs to notice.
    service.ingest(_event(service))
    (baris,) = service.recap("2026-09-10")
    assert baris["truck_id"] is None and baris["total"] == 1
    assert baris["net_kg"] is None


# ── pagination riwayat grading ────────────────────────────────────────────────


def test_inspection_count_covers_the_whole_day_not_one_page(service):
    """Angka total tidak boleh datang dari `len(items)`: itu cuma sepanjang halaman,
    jadi layar akan menulis "25 baris" di hari yang punya delapan ratus."""
    for i in range(7):
        service.ingest(_event(service, event_id=f"ev-{i}"))

    assert service.store.inspection_count("2026-09-10") == 7
    # Halaman pertama dibatasi, hitungannya tidak.
    assert len(service.store.inspections("2026-09-10", limit=3)) == 3
    assert service.store.inspection_count("2026-09-10") == 7


def test_inspection_count_uses_the_same_filter_as_the_rows(service):
    """Hitungan yang mengabaikan filter bikin halaman 4 dari 1 halaman yang ada:
    tombol Berikutnya hidup, halamannya kosong."""
    lain = service.lines[1].machine_id
    for i in range(4):
        service.ingest(_event(service, event_id=f"a-{i}"))
    for i in range(2):
        service.ingest(_event(service, event_id=f"b-{i}", machine_id=lain))

    satu = service.lines[0].line_code
    assert service.store.inspection_count("2026-09-10", line_code=satu) == 4
    assert service.store.inspection_count("2026-09-10", line_code=service.lines[1].line_code) == 2
    assert service.store.inspection_count("2026-09-10") == 6


def test_inspection_count_is_zero_on_an_empty_day(service):
    assert service.store.inspection_count("2026-09-10") == 0


def test_history_membawa_total_supaya_layar_bisa_menghitung_halaman(service):
    for i in range(5):
        service.ingest(_event(service, event_id=f"ev-{i}"))

    hasil = service.history_halaman("2026-09-10", limit=2, offset=0)
    assert hasil["total"] == 5
    assert len(hasil["items"]) == 2

    # Halaman terakhir: sisa satu baris, totalnya tetap sama.
    akhir = service.history_halaman("2026-09-10", limit=2, offset=4)
    assert akhir["total"] == 5
    assert len(akhir["items"]) == 1


# ── lantai berat: angka mustahil harus tertahan ──────────────────────────────


def test_bruto_seratus_kilo_ditolak(service):
    """Terlihat di layar pabrik: satu baris bruto 100 kg lolos, karena lantainya
    100.0 dan perbandingannya `<`. Truk kosong saja belasan ton — 100 kg itu salah
    ketik, dan neto yang lahir darinya dibayar ke petani."""
    with pytest.raises(OperatorError) as kena:
        service.record_weighing({
            "plate_number": "BE 4412 OFL", "gross_kg": 100,
            "entered_at": "2026-09-15T08:00:00+07:00",
        })
    assert kena.value.code == DI_BAWAH_MINIMUM


def test_berat_setengah_ton_masih_ditolak(service):
    """500 kg pun bukan truk. Lantai yang terlalu rendah cuma menangkap nol."""
    with pytest.raises(OperatorError):
        service.record_weighing({
            "plate_number": "BE 4412 OFL", "gross_kg": 500,
            "entered_at": "2026-09-15T08:00:00+07:00",
        })


def test_truk_kosong_paling_ringan_tetap_diterima(service):
    """Colt Diesel kosong sekitar 2,5 ton. Lantai tidak boleh menolak truk sungguhan
    yang paling ringan — itu menghalangi pekerjaan, bukan menjaganya."""
    hasil = service.record_weighing({
        "plate_number": "BE 4412 OFL", "gross_kg": 2500,
        "entered_at": "2026-09-15T08:00:00+07:00",
    })
    assert hasil["gross_kg"] == 2500.0


# ── manifest janjang R2: visit() + bunches_for_assignment() ─────────────────


def _inspection_row(**over) -> dict:
    """A row shaped exactly like `add_inspection`'s INSERT requires — see the
    same helper pattern in `test_erp_queue.py` / `test_rekonsiliasi_truk.py`."""
    row = {
        "event_id": "e-1",
        "machine_id": "m-1",
        "line_code": "line-1",
        "work_date": "2026-09-16",
        "timestamp": "2026-09-16T08:01:00+07:00",
        "ripeness_status": "ACC",
        "ripeness_confidence": 0.9,
        "capture_type": "auto",
        "image_path": "captures/results/2026-09-16/f.webp",
        "truck_id": None,
        "assignment_id": "a-1",
        "prediction": "Acc",
        "tp_status": None,
        "tp_confidence": None,
    }
    row.update(over)
    return row


def test_bunches_for_assignment_come_back_in_time_order(tmp_path):
    store = ConsoleStore(tmp_path / "c.db")
    store.add_inspection(_inspection_row(event_id="e-2", timestamp="2026-09-16T08:02:00+07:00"))
    store.add_inspection(_inspection_row(event_id="e-1", timestamp="2026-09-16T08:01:00+07:00"))
    store.add_inspection(
        _inspection_row(event_id="e-9", timestamp="2026-09-16T08:03:00+07:00", assignment_id="lain")
    )
    assert [b["event_id"] for b in store.bunches_for_assignment("a-1")] == ["e-1", "e-2"]


def test_bunches_for_assignment_carries_every_key_the_manifest_reads(tmp_path):
    # build_manifest() reads these off each bunch row (task-B3 brief). Missing
    # one means the manifest silently renders with a hole in it.
    store = ConsoleStore(tmp_path / "c.db")
    store.add_inspection(_inspection_row(grade_class="Ripe", tp_confidence=0.91))
    (bunch,) = store.bunches_for_assignment("a-1")
    for key in (
        "event_id", "machine_id", "timestamp", "ripeness_status", "ripeness_confidence",
        "capture_type", "grade_class", "tp_confidence", "image_path",
    ):
        assert key in bunch, key


def test_visit_carries_supplier_name(tmp_path):
    store = ConsoleStore(tmp_path / "c.db")
    store.upsert_supplier({"id": "s1", "name": "KUD Sumber Makmur", "source_group": "Plasma", "status": "active"})
    store.upsert_truck({"id": "t1", "plate_number": "BE 1 AA", "supplier_id": "s1", "status": "active"})
    store.upsert_weighing({
        "id": "w1", "ref": "r1", "plate_number": "BE 1 AA", "plate_norm": "BE1AA", "truck_id": "t1",
        "work_date": "2026-09-16", "gross_kg": 15000.0, "tare_kg": 5000.0, "net_kg": 10000.0,
        "entered_at": "2026-09-16T08:00:00+07:00", "exited_at": None,
    })
    assert store.visit("w1")["supplier_name"] == "KUD Sumber Makmur"


def test_operator_baru_default_operator(tmp_path):
    """No account gains privilege through migration alone."""
    store = ConsoleStore(tmp_path / "c.db")
    store.upsert_operator_manual(
        {"email": "a@b.c", "full_name": "A", "password_hash": "scrypt$x"}
    )
    assert store.operator_by_email("a@b.c")["role"] == "operator"


def test_peran_ikut_di_baris_sesi(tmp_path):
    """The route guard reads `role` off the session row, so it must carry it."""
    store = ConsoleStore(tmp_path / "c.db")
    oid = store.upsert_operator_manual(
        {"email": "s@b.c", "full_name": "S", "password_hash": "scrypt$x"}
    )
    store.set_role(oid, "support")
    store.create_session("tok", oid, now=1000.0, ttl_s=3600)
    assert store.session("tok", now=1001.0)["role"] == "support"


def test_migrasi_menambah_peran_ke_db_lama(tmp_path):
    """A factory PC already running has a table without this column."""
    import sqlite3

    db_path = tmp_path / "lama.db"
    db = sqlite3.connect(str(db_path))
    db.execute(
        """CREATE TABLE operators (
               id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, full_name TEXT NOT NULL,
               password_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
               origin TEXT NOT NULL DEFAULT 'lokal', erp_name TEXT,
               created_at REAL NOT NULL, fail_count INTEGER NOT NULL DEFAULT 0,
               last_failed_at REAL)"""
    )
    db.execute(
        "INSERT INTO operators (id, email, full_name, password_hash, created_at)"
        " VALUES ('i1', 'lama@b.c', 'Lama', 'scrypt$x', 1.0)"
    )
    db.commit()
    db.close()

    store = ConsoleStore(db_path)
    assert store.operator_by_email("lama@b.c")["role"] == "operator"


def test_set_peran_menolak_nilai_asing(tmp_path):
    """An unrecognized value must not settle into the access-gating column."""
    store = ConsoleStore(tmp_path / "c.db")
    oid = store.upsert_operator_manual(
        {"email": "x@b.c", "full_name": "X", "password_hash": "scrypt$x"}
    )
    store.set_role(oid, "admin")
    assert store.operator_by_email("x@b.c")["role"] == "operator"


def test_has_support_account_false_with_no_operators_at_all(tmp_path):
    store = ConsoleStore(tmp_path / "c.db")
    assert store.has_support_account() is False


def test_has_support_account_false_when_all_are_operators(tmp_path):
    """The exact trap this method exists to catch: every account on `operator`,
    none able to open the screen that would promote another one."""
    store = ConsoleStore(tmp_path / "c.db")
    store.upsert_operator_manual(
        {"email": "op@b.c", "full_name": "Operator", "password_hash": "scrypt$x"}
    )
    assert store.has_support_account() is False


def test_has_support_account_true_once_one_account_is_promoted(tmp_path):
    store = ConsoleStore(tmp_path / "c.db")
    oid = store.upsert_operator_manual(
        {"email": "s@b.c", "full_name": "S", "password_hash": "scrypt$x"}
    )
    store.set_role(oid, "support")
    assert store.has_support_account() is True


def test_has_support_account_false_when_the_support_account_is_off(tmp_path):
    """A switched-off account cannot sign in, so it does not count as an escape
    hatch — same rule `operators()` already applies to the sign-in list."""
    store = ConsoleStore(tmp_path / "c.db")
    oid = store.upsert_operator_manual(
        {"email": "s@b.c", "full_name": "S", "password_hash": "scrypt$x"}
    )
    store.set_role(oid, "support")
    store.set_operator_status(oid, "off")
    assert store.has_support_account() is False


def test_tarikan_erp_menulis_peran_yang_diizinkan(tmp_path):
    store = ConsoleStore(tmp_path / "c.db", erp_allowed_roles=frozenset({"support"}))
    store.upsert_operator_erp(
        {"email": "s@erp.c", "full_name": "S", "password_hash": "x",
         "erp_name": "s@erp.c", "active": 1, "role": "support"}
    )
    assert store.operator_by_email("s@erp.c")["role"] == "support"


def test_daftar_izin_kosong_membuang_peran_dari_erp(tmp_path):
    """Factory-side brake: an empty .env means no ERP account can be promoted."""
    store = ConsoleStore(tmp_path / "c.db", erp_allowed_roles=frozenset())
    store.upsert_operator_erp(
        {"email": "s@erp.c", "full_name": "S", "password_hash": "x",
         "erp_name": "s@erp.c", "active": 1, "role": "support"}
    )
    assert store.operator_by_email("s@erp.c")["role"] == "operator"


def test_tarikan_erp_tidak_menurunkan_peran_akun_lokal(tmp_path):
    """The local account is the way in when the internet is down; ERP must not touch it."""
    store = ConsoleStore(tmp_path / "c.db", erp_allowed_roles=frozenset({"support"}))
    oid = store.upsert_operator_manual(
        {"email": "support@autograde.local", "full_name": "S", "password_hash": "scrypt$x"}
    )
    store.set_role(oid, "support")
    store.upsert_operator_erp(
        {"email": "support@autograde.local", "full_name": "S", "password_hash": "y",
         "erp_name": "s", "active": 1, "role": "operator"}
    )
    assert store.operator_by_email("support@autograde.local")["role"] == "support"


def test_reset_sandi_lokal_tidak_menghapus_peran(tmp_path):
    """`make operator` resets a password through the same upsert used to create
    the account; that upsert must not silently demote the account's role too."""
    store = ConsoleStore(tmp_path / "c.db")
    oid = store.upsert_operator_manual(
        {"email": "support@autograde.local", "full_name": "S", "password_hash": "scrypt$lama"}
    )
    store.set_role(oid, "support")

    store.upsert_operator_manual(
        {"email": "support@autograde.local", "full_name": "S", "password_hash": "scrypt$baru"}
    )

    row = store.operator_by_email("support@autograde.local")
    assert row["role"] == "support"
    assert row["password_hash"] == "scrypt$baru", "sandi tetap harus terganti"


def test_migration_renames_every_indonesian_column_not_just_operators(tmp_path):
    """A console database written before the rename keeps ALL its old names.

    The first fix only carried `operators`, so `sesi` and `weighings` still held
    `kedaluwarsa_at` and `bruto_kg` — every sign-in died on `no such column:
    s.expires_at` and the screen answered 500 before anyone could log in.
    """
    import sqlite3

    db_path = tmp_path / "lama.db"
    db = sqlite3.connect(str(db_path))
    db.executescript(
        """
        CREATE TABLE sesi (token TEXT PRIMARY KEY, operator_id TEXT NOT NULL,
            dibuat_at REAL NOT NULL, kedaluwarsa_at REAL NOT NULL);
        CREATE TABLE weighings (id TEXT PRIMARY KEY, ref TEXT, plate_number TEXT,
            plate_norm TEXT, truck_id TEXT, tanggal_kerja TEXT, bruto_kg REAL,
            tara_kg REAL, neto_kg REAL, waktu_masuk TEXT, waktu_keluar TEXT,
            received_at REAL);
        CREATE TABLE suppliers (id TEXT PRIMARY KEY, name TEXT, sumber TEXT);
        CREATE TABLE inspections (event_id TEXT PRIMARY KEY, tanggal_kerja TEXT,
            line_code TEXT, timestamp TEXT);
        INSERT INTO weighings (id, plate_number, plate_norm, tanggal_kerja, bruto_kg,
            tara_kg, neto_kg, waktu_masuk, received_at)
        VALUES ('w1', 'BE 1 A', 'BE1A', '2026-09-15', 12480.0, 5120.0, 7360.0,
                '2026-09-15T08:00:00+07:00', 1.0);
        """
    )
    db.commit()
    db.close()

    store = ConsoleStore(db_path)

    def columns(table):
        with store._lock:
            return {r["name"] for r in store._db.execute(f"PRAGMA table_info({table})")}

    assert {"created_at", "expires_at"} <= columns("sesi")
    assert {"work_date", "gross_kg", "tare_kg", "net_kg", "entered_at"} <= columns("weighings")
    assert "source_group" in columns("suppliers")
    assert "work_date" in columns("inspections")

    # The numbers a mill gets paid on must survive the rename untouched.
    with store._lock:
        row = store._db.execute(
            "SELECT gross_kg, tare_kg, net_kg FROM weighings WHERE id = 'w1'"
        ).fetchone()
    assert (row["gross_kg"], row["tare_kg"], row["net_kg"]) == (12480.0, 5120.0, 7360.0)
