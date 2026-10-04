"""Lepas paksa on the console service (2026-10-04).

Rule 13 keeps a truck on a line until the line hears the release. A dead line can never
hear it, so the truck stayed: Update now refused (rule 38), automatic assignment held
(rule 36), and the line, once back, pulled the departed truck again. Lepas paksa clears it
on the console ONLY when the line gives no answer at all, with the same bookkeeping as a
normal release, and sends the release again once a line that was only cut off answers.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.lepas_paksa import KUNCI_LEPAS_PAKSA
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services import lepas_paksa as layanan
from palmgrade.services.console_service import ConsoleService

PLAT = "BE 1234 XY"
LINE = "line-1"
OLEH = "Pak Budi (budi@pks.test)"


class FakeLine:
    """`LineClient.assign_truck` with the three ways a line can take a release."""

    def __init__(self) -> None:
        self.kiriman: list[tuple[str, str, str]] = []
        self.mode = "jawab"  # jawab | mati | menolak | lambat
        self.kunci_saat_kirim: list[bool] = []
        self.service: ConsoleService | None = None

    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None) -> None:
        if self.service is not None:
            self.kunci_saat_kirim.append(self.service.kunci_line(line.line_code).locked())
        if self.mode == "mati":
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line did not answer", line=line.name)
        if self.mode == "menolak":
            raise LineUnavailable(LINE_MENOLAK, "line refused: HTTP 409", line=line.name, status=409)
        if self.mode == "lambat":
            await asyncio.sleep(5)
        self.kiriman.append((line.line_code, assignment_id, truck_id))


class FakeErp:
    def __init__(self) -> None:
        self.kunjungan: list[str] = []

    def visit(self, weighing_id, *, tz) -> None:
        self.kunjungan.append(weighing_id)

    def truck(self, *_a, **_kw) -> None:
        """A manual truck goes up to AutoERP too; not what these tests count."""


def _service(tmp_path, line: FakeLine | None = None, erp: FakeErp | None = None) -> ConsoleService:
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    line = line or FakeLine()
    service = ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), line, erp_queue=erp)
    line.service = service
    return service


def _truk_di_line(service: ConsoleService, *, timbang: bool = True) -> dict:
    """A truck weighed in (so its visit ticket exists) and assigned to line-1."""
    truk = service.register_manual_truck(PLAT)
    if timbang:
        jam = datetime.now(ZoneInfo("Asia/Jakarta")).replace(microsecond=0).isoformat()
        asyncio.run(service.record_weighing({"plate_number": PLAT, "gross_kg": "14000", "entered_at": jam}))
    asyncio.run(service.assign_truck(LINE, truk["id"]))
    return service.store.assignments()[LINE]


def _paksa(service: ConsoleService) -> dict:
    return asyncio.run(service.force_release(LINE, oleh=OLEH))


# ── the line gives no answer at all ─────────────────────────────────────────


def test_a_dead_line_is_cleared_on_the_console_and_its_grading_linked_to_the_visit(tmp_path):
    erp = FakeErp()
    service = _service(tmp_path, erp=erp)
    pegangan = _truk_di_line(service)
    erp.kunjungan.clear()
    service.line_client.mode = "mati"

    hasil = _paksa(service)

    assert hasil["paksa"] is True and hasil["truck_id"] is None
    assert not service.store.assignments()[LINE]["truck_id"]
    tiket = service.store.weighing_for_assignment(pegangan["assignment_id"])
    assert tiket is not None, "the grading must be linked to the visit ticket, as Lepas does"
    assert erp.kunjungan == [tiket], "the visit is queued once, exactly as Lepas queues it"


def test_a_line_that_hangs_past_the_short_wait_counts_as_not_answering(tmp_path, monkeypatch):
    monkeypatch.setattr(layanan, "TIMEOUT_LEPAS_PAKSA_S", 0.05)
    service = _service(tmp_path)
    _truk_di_line(service)
    service.line_client.mode = "lambat"

    assert _paksa(service)["paksa"] is True
    assert not service.store.assignments()[LINE]["truck_id"]


def test_one_warning_names_the_account_the_line_and_the_plate(tmp_path, caplog):
    service = _service(tmp_path)
    _truk_di_line(service)
    service.line_client.mode = "mati"

    with caplog.at_level(logging.INFO, logger=layanan.__name__):
        _paksa(service)

    peringatan = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(peringatan) == 1, [r.getMessage() for r in peringatan]
    pesan = peringatan[0].getMessage()
    assert OLEH in pesan and LINE in pesan and PLAT in pesan


def test_a_forced_release_without_a_ticket_still_clears_the_line(tmp_path):
    """A truck put on by hand with no weighing: nothing to link, the line is still freed."""
    service = _service(tmp_path)
    _truk_di_line(service, timbang=False)
    service.line_client.mode = "mati"

    assert _paksa(service)["paksa"] is True
    assert not service.store.assignments()[LINE]["truck_id"]


# ── the line answers ────────────────────────────────────────────────────────


def test_a_line_that_answers_gets_the_normal_release_and_nothing_is_forced(tmp_path, caplog):
    erp = FakeErp()
    service = _service(tmp_path, erp=erp)
    _truk_di_line(service)
    erp.kunjungan.clear()

    with caplog.at_level(logging.WARNING, logger=layanan.__name__):
        hasil = _paksa(service)

    assert hasil["paksa"] is False
    assert service.line_client.kiriman[-1] == (LINE, "", "")
    assert not service.store.assignments()[LINE]["truck_id"]
    assert len(erp.kunjungan) == 1
    assert service.store.get_state(KUNCI_LEPAS_PAKSA) in (None, "{}")
    assert not caplog.records, "a normal release is not a forced one"


def test_a_line_that_answers_with_a_refusal_is_never_forced(tmp_path):
    service = _service(tmp_path)
    _truk_di_line(service)
    service.line_client.mode = "menolak"

    with pytest.raises(LineUnavailable) as galat:
        _paksa(service)

    assert galat.value.code == LINE_MENOLAK
    assert service.store.assignments()[LINE]["truck_id"], "a refusing line still holds its truck"
    assert service.store.get_state(KUNCI_LEPAS_PAKSA) in (None, "{}")


def test_no_truck_on_the_line_sends_nothing(tmp_path):
    service = _service(tmp_path)
    service.line_client.mode = "mati"

    hasil = _paksa(service)

    assert hasil["paksa"] is False and hasil["truck_id"] is None
    assert service.line_client.kiriman == []


def test_an_unknown_line_is_refused(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(service.force_release("line-9", oleh=OLEH))


# ── the line answers again (cut off, not dead) ──────────────────────────────


def _dipaksa(tmp_path) -> tuple[ConsoleService, str]:
    service = _service(tmp_path)
    truck_id = _truk_di_line(service)["truck_id"]
    service.line_client.mode = "mati"
    _paksa(service)
    service.line_client.mode = "jawab"
    service.line_client.kiriman.clear()
    return service, truck_id


def test_a_line_back_from_a_cut_still_holding_the_truck_gets_the_release_again(tmp_path, caplog):
    service, truck_id = _dipaksa(tmp_path)

    with caplog.at_level(logging.WARNING, logger=layanan.__name__):
        asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))

    assert service.line_client.kiriman == [(LINE, "", "")]
    assert any(LINE in r.getMessage() and PLAT in r.getMessage() for r in caplog.records)
    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": None}))
    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))
    assert len(service.line_client.kiriman) == 1, "done once, then forgotten"


def test_a_line_that_restarted_empty_needs_nothing(tmp_path):
    service, truck_id = _dipaksa(tmp_path)

    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": None}))
    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))

    assert service.line_client.kiriman == []


def test_the_same_truck_put_back_on_by_the_operator_is_left_alone(tmp_path):
    service, truck_id = _dipaksa(tmp_path)
    asyncio.run(service.assign_truck(LINE, truck_id))
    service.line_client.kiriman.clear()

    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))

    assert service.line_client.kiriman == []
    assert service.store.assignments()[LINE]["truck_id"] == truck_id


def test_a_failed_resend_stays_pending_for_the_next_poll(tmp_path):
    service, truck_id = _dipaksa(tmp_path)
    service.line_client.mode = "menolak"
    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))
    service.line_client.mode = "jawab"

    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))

    assert service.line_client.kiriman == [(LINE, "", "")]


def test_no_resend_while_an_assign_to_that_line_is_in_flight(tmp_path):
    """The line may already hold the new truck while the console has not written it yet."""
    service, truck_id = _dipaksa(tmp_path)

    async def skenario() -> None:
        async with service.kunci_line(LINE):
            await service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id})

    asyncio.run(skenario())
    assert service.line_client.kiriman == []
    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))
    assert service.line_client.kiriman == [(LINE, "", "")], "still pending after the assign is done"


def test_assign_holds_the_line_lock_while_the_line_answers(tmp_path):
    service = _service(tmp_path)
    _truk_di_line(service)
    assert service.line_client.kunci_saat_kirim[-1] is True


def test_the_pending_release_survives_a_console_restart(tmp_path):
    service, truck_id = _dipaksa(tmp_path)
    baru = _service(tmp_path)

    asyncio.run(baru.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))

    assert baru.line_client.kiriman == [(LINE, "", "")]


def test_a_line_with_nothing_pending_is_never_written_to(tmp_path):
    service = _service(tmp_path)
    truck_id = _truk_di_line(service)["truck_id"]
    service.line_client.kiriman.clear()
    asyncio.run(service.cocokkan_lepas_paksa(LINE, {"truck_id": truck_id}))
    assert service.line_client.kiriman == []
