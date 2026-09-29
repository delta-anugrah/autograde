"""Wiring the AutoERP link, and what AutoERP's answers do locally.

The composition root decides whether the link exists at all: no `ERP_URL`, no
workers, no traffic — the operator screen must never depend on AutoERP.
"""
from __future__ import annotations

from dataclasses import replace
from zoneinfo import ZoneInfo

from palmgrade.core.config import Settings
from palmgrade.domain.erp_master import supplier_id_for
from palmgrade.domain.plate import truck_id_for
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.erp_queue import ErpQueue
from palmgrade.workers.erp_link import build_erp_workers, outbox_handlers, truck_linked, visit_recorded
from palmgrade.workers.erp_outbox_worker import ErpOutboxWorker
from palmgrade.workers.master_data_worker import MasterDataWorker
from palmgrade.workers.visit_resend_worker import VisitResendWorker

PLATE = "BE 1 AA"
WIB = ZoneInfo("Asia/Jakarta")


def _parts(tmp_path) -> tuple[ConsoleStore, ErpQueue]:
    store = ConsoleStore(tmp_path / "console.db")
    return store, ErpQueue(store, ErpOutboxStore(tmp_path / "erp_outbox.db"))


def _weighing(store: ConsoleStore, weighing_id: str = "w1") -> str:
    store.upsert_weighing(
        {
            "id": weighing_id, "ref": "SCL-1", "plate_number": PLATE, "plate_norm": "BE1AA",
            "truck_id": truck_id_for(PLATE), "work_date": "2026-09-13",
            "gross_kg": 14560.0, "tare_kg": None, "net_kg": None,
            "entered_at": "2026-09-13T07:41:00+07:00", "exited_at": None,
        }
    )
    return weighing_id


def test_without_an_erp_url_there_are_no_workers(tmp_path):
    store, queue = _parts(tmp_path)

    assert build_erp_workers(replace(Settings(), erp_url=""), store, queue) == []


def test_an_erp_url_starts_the_pull_the_outbox_and_the_daily_resend(tmp_path):
    store, queue = _parts(tmp_path)
    settings = replace(
        Settings(), erp_url="http://erp.local", erp_api_key="k", erp_api_secret="s"
    )

    workers = build_erp_workers(settings, store, queue)

    assert [type(worker) for worker in workers] == [
        MasterDataWorker, ErpOutboxWorker, VisitResendWorker,
    ]


def test_a_truck_autoerp_accepted_is_linked_to_its_erp_name(tmp_path):
    """`erp_name` is what the visit is sent under later; losing it makes the
    ticket unmatchable on the ERP side."""
    store, _ = _parts(tmp_path)
    store.upsert_truck({"id": truck_id_for("be 1 aa"), "plate_number": "be 1 aa", "status": "manual"})

    truck_linked(store)("BE1AA", {"name": PLATE, "supplier": None, "vehicle_class": ""})

    row = store.truck(truck_id_for(PLATE))
    assert (row["erp_name"], row["supplier_id"]) == (PLATE, None)


def test_a_plate_autoerp_already_knew_brings_its_owner_back(tmp_path):
    """AutoERP answers with the owner it already has; the console shows it at
    once instead of waiting for the truck to be touched upstream again."""
    store, _ = _parts(tmp_path)
    store.upsert_truck({"id": truck_id_for(PLATE), "plate_number": PLATE, "status": "manual"})

    truck_linked(store)("BE1AA", {"name": PLATE, "supplier": "KUD Sumber Makmur"})

    assert store.truck(truck_id_for(PLATE))["supplier_id"] == supplier_id_for("KUD Sumber Makmur")


def test_the_ticket_autoerp_made_is_kept_against_the_weighing(tmp_path):
    """The trace from a weighbridge row at the mill to the receipt in the ledger."""
    store, _ = _parts(tmp_path)
    _weighing(store)

    visit_recorded(store, tz=WIB)("w1", {"ticket": "WB-2026-03851", "status": "Waiting Grading"})

    row = store.weighing("w1")
    assert (row["erp_ticket"], row["erp_status"]) == ("WB-2026-03851", "Waiting Grading")


def test_a_revision_after_finalisation_is_recorded_and_logged(tmp_path, caplog):
    """AutoERP never rewrites a finalised ticket: it flags `grading_revised`, leaves a
    comment, and says so in `note`. Keeping only the ticket number threw that away, so
    nobody at the mill could tell that the numbers they sent were not the booked ones.
    """
    store, _ = _parts(tmp_path)
    _weighing(store)

    with caplog.at_level("WARNING"):
        visit_recorded(store, tz=WIB)(
            "w1",
            {
                "ticket": "WB-2026-03851",
                "status": "Finalised",
                "revised": True,
                "note": "ticket already finalised; grading revised",
            },
        )

    row = store.weighing("w1")
    assert (row["erp_status"], row["erp_note"]) == (
        "Finalised",
        "ticket already finalised; grading revised",
    )
    assert "grading revised" in caplog.text


def test_a_cancelled_ticket_is_recorded_as_such(tmp_path):
    """`note: ticket cancelled; visit ignored` means AutoERP took nothing from this
    send. Marking it delivered without the note reads as success."""
    store, _ = _parts(tmp_path)
    _weighing(store)

    visit_recorded(store, tz=WIB)(
        "w1", {"ticket": "WB-2026-03851", "status": "Cancelled", "note": "ticket cancelled; visit ignored"}
    )

    assert store.weighing("w1")["erp_note"] == "ticket cancelled; visit ignored"


def test_an_answer_for_a_weighing_we_no_longer_have_is_harmless(tmp_path):
    """The row can be gone by the time the outbox drains; recording must not raise."""
    store, _ = _parts(tmp_path)

    visit_recorded(store, tz=WIB)("w1", {"note": "ticket cancelled; visit ignored"})


def test_the_worker_and_the_tests_share_one_handler_map(tmp_path):
    store, _ = _parts(tmp_path)

    handlers = outbox_handlers(store, tz=WIB)

    assert {kind: h.method for kind, h in handlers.items()} == {
        "truck": "erpnext.palm_mill.api.upsert_truck",
        "visit": "erpnext.palm_mill.api.upsert_visit",
    }


# ── batch 2.3: only answers a human must act on reach the Log tab ────────────


def _janjang(
    store: ConsoleStore, event_id: str, *, line_code: str, assignment_id: str, status: str = "ACC"
) -> None:
    store.add_inspection({
        "event_id": event_id, "machine_id": "m-2", "line_code": line_code, "work_date": "2026-09-13",
        "timestamp": "2026-09-13T07:58:00+07:00", "ripeness_status": status,
        "ripeness_confidence": 0.9, "capture_type": "auto", "image_path": None,
        "truck_id": truck_id_for(PLATE), "assignment_id": assignment_id,
        "prediction": "Acc" if status == "ACC" else "Rej",
        "tp_status": None, "tp_confidence": None,
    })


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


def test_tiket_final_yang_berbeda_dicatat_dengan_kode_line_jam_dan_tindakan(tmp_path, caplog):
    store, _ = _parts(tmp_path)
    _weighing(store)
    store.link_weighing_to_assignment("w1", "a1")
    _janjang(store, "ev-1", line_code="line-2", assignment_id="a1")

    with caplog.at_level("WARNING"):
        visit_recorded(store, tz=WIB)("w1", {
            "ticket": "WB-2026-03851", "status": "Finalised", "revised": True,
            "note": "ticket already finalised; grading revised",
        })

    [pesan] = _warnings(caplog)
    assert pesan.startswith("[TIKET_FINAL_BERBEDA] Truk BE 1 AA, line-2, timbang masuk 2026-09-13 07:41: ")
    assert "WB-2026-03851" in pesan and "Tindakan: " in pesan


def test_visit_unchanged_tidak_masuk_tab_log(tmp_path, caplog):
    """Kirim ulang harian menjawab ini untuk SETIAP tiket final kemarin: bukan berita."""
    store, _ = _parts(tmp_path)
    _weighing(store)

    with caplog.at_level("INFO"):
        visit_recorded(store, tz=WIB)("w1", {
            "ticket": "WB-2026-03851", "status": "Finalised",
            "note": "ticket already finalised; visit unchanged",
        })

    assert _warnings(caplog) == []
    assert store.weighing("w1")["erp_note"] == "ticket already finalised; visit unchanged"


def test_tiket_dibatalkan_masuk_tab_log_dengan_kodenya(tmp_path, caplog):
    store, _ = _parts(tmp_path)
    _weighing(store)

    with caplog.at_level("WARNING"):
        visit_recorded(store, tz=WIB)("w1", {"ticket": "WB-2026-03851", "status": "Cancelled",
                                     "note": "ticket cancelled; visit ignored"})

    [pesan] = _warnings(caplog)
    assert pesan.startswith("[TIKET_DIBATALKAN] Truk BE 1 AA, -, timbang masuk 2026-09-13 07:41: ")


def test_jawaban_yang_sama_dari_kirim_ulang_tidak_dicatat_dua_kali(tmp_path, caplog):
    """AutoERP membandingkan dengan angka yang DIBUKUKAN, jadi tiap kirim ulang rekap yang
    sama menjawab "grading revised" lagi. Sekali per perubahan, bukan sekali per kiriman;
    kalimat baru (bobot ikut berubah) tetap dicatat."""
    store, _ = _parts(tmp_path)
    _weighing(store)
    revisi = {"ticket": "WB-2026-03851", "status": "Finalised", "revised": True,
              "note": "ticket already finalised; grading revised"}

    with caplog.at_level("INFO"):
        visit_recorded(store, tz=WIB)("w1", revisi)
        visit_recorded(store, tz=WIB)("w1", revisi)
        visit_recorded(store, tz=WIB)("w1", revisi | {"note": "ticket already finalised; grading revised, weights revised"})

    assert [p.split("]")[0] for p in _warnings(caplog)] == ["[TIKET_FINAL_BERBEDA", "[TIKET_FINAL_BERBEDA"]
    assert "grading revised, weights revised" in _warnings(caplog)[1]


def test_jam_timbang_masuk_ditulis_jam_pabrik_walau_layar_mengirim_utc(tmp_path, caplog):
    """Tombol Timbang masuk mengirim `new Date().toISOString()`; tab Log harus sama dengan
    jam yang dibaca operator di baris Timbangan, bukan jam UTC."""
    store, _ = _parts(tmp_path)
    store.upsert_weighing({
        "id": "w1", "ref": "SCL-1", "plate_number": PLATE, "plate_norm": "BE1AA",
        "truck_id": truck_id_for(PLATE), "work_date": "2026-09-14", "gross_kg": 14560.0,
        "tare_kg": None, "net_kg": None, "entered_at": "2026-09-13T18:30:00.000Z", "exited_at": None,
    })

    with caplog.at_level("WARNING"):
        visit_recorded(store, tz=WIB)("w1", {"ticket": "WB-1", "status": "Cancelled",
                                             "note": "ticket cancelled; visit ignored"})

    [pesan] = _warnings(caplog)
    assert "timbang masuk 2026-09-14 01:30: " in pesan


def test_pesan_membawa_rekap_pabrik_dan_tiket_tanpa_nomor_ditulis_netral(tmp_path, caplog):
    store, _ = _parts(tmp_path)
    _weighing(store)
    store.link_weighing_to_assignment("w1", "a1")
    _janjang(store, "ev-1", line_code="line-2", assignment_id="a1")
    _janjang(store, "ev-2", line_code="line-2", assignment_id="a1", status="REJ")

    with caplog.at_level("WARNING"):
        visit_recorded(store, tz=WIB)("w1", {"revised": True, "note": "ticket already finalised; grading revised"})

    [pesan] = _warnings(caplog)
    assert "tiket AutoERP (tanpa nomor) sudah final" in pesan and " - " not in pesan
    assert "Yang berbeda: grading berubah. Rekap pabrik sekarang: 2 janjang, mentah 50%. " in pesan
