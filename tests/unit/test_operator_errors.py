"""Failures the operator reads come back as a code, not a sentence.

The console screen is bilingual; a server sentence is not. Glued together they
read "Failed: line-1 tidak menjawab: All connection attempts failed" — three
languages' worth of one error. Guarded here: every failure the operator screen
can trigger carries a stable code plus the numbers it needs, the old text stays
for logs and machine callers, and it is still a ValueError where a 400 is owed.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from palmgrade.core.config import Settings
from palmgrade.domain import operator_error as code
from palmgrade.domain.operator_error import InvalidInput, OperatorError
from palmgrade.integrations.notifications.line_client import LineClient, LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import MINIMUM_WEIGHT_KG, ConsoleService


class SilentLine:
    async def assign_truck(self, *_a, **_kw) -> None:
        return None


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), SilentLine())


def _weigh(service, **overrides):
    return service.record_weighing(
        {"plate_number": "B 1234 XY", "ref": "T-1", "entered_at": "2026-09-14T08:00:00+07:00", **overrides}
    )


def _fails(func) -> OperatorError:
    with pytest.raises(OperatorError) as caught:
        func()
    return caught.value


def test_unknown_line_carries_code_and_line_name(service):
    err = _fails(lambda: asyncio.run(service.assign_truck("line-9", "t")))
    assert (err.code, err.params) == (code.LINE_TIDAK_DIKENAL, {"line": "line-9"})
    assert isinstance(err, ValueError)  # the route still answers 404


def test_empty_plate_carries_a_code(service):
    err = _fails(lambda: service.register_manual_truck("  "))
    assert err.code == code.PLAT_KOSONG
    assert isinstance(err, ValueError)


def test_non_numeric_gross_names_the_field_and_its_value(service):
    err = _fails(lambda: _weigh(service, gross_kg="abc"))
    assert (err.code, err.params) == (code.BUKAN_ANGKA, {"field": "gross_kg", "value": "abc"})


def test_negative_weight_names_its_field(service):
    err = _fails(lambda: _weigh(service, gross_kg="-5"))
    assert (err.code, err.params) == (code.NEGATIF, {"field": "gross_kg", "value": -5.0})


def test_weight_below_minimum_carries_a_number_not_text(service):
    # Numbers, not strings: the screen formats them with the operator's decimal mark.
    err = _fails(lambda: _weigh(service, gross_kg="14,82"))
    assert err.code == code.DI_BAWAH_MINIMUM
    assert err.params == {"field": "gross_kg", "value": 14.82, "minimum": MINIMUM_WEIGHT_KG}


def test_tare_greater_than_gross_carries_both(service):
    _weigh(service, gross_kg="14000")
    err = _fails(lambda: _weigh(service, tare_kg="15000", exited_at="2026-09-14T09:00:00+07:00"))
    assert (err.code, err.params) == (code.TARA_LEBIH_BESAR, {"tara": 15000.0, "bruto": 14000.0})


def test_old_message_still_exists_for_logs_and_the_scale_program(service):
    err = _fails(lambda: _weigh(service, gross_kg="abc"))
    assert str(err) == "gross_kg bukan angka: 'abc'"


def test_detail_carries_code_params_and_message():
    err = InvalidInput(code.PLAT_KOSONG, "nomor polisi tidak boleh kosong")
    assert err.as_detail() == {
        "code": "plat_kosong",
        "params": {},
        "message": "nomor polisi tidak boleh kosong",
    }


def _line_client(handler) -> tuple[LineClient, object]:
    settings = Settings()
    return LineClient(settings, transport=httpx.MockTransport(handler)), settings.console_lines[0]


def test_unresponsive_line_carries_code_and_line_name():
    def disconnected(request):
        raise httpx.ConnectError("All connection attempts failed", request=request)

    client, line = _line_client(disconnected)
    err = _fails(lambda: asyncio.run(
        client.assign_truck(line, assignment_id="a", truck_id="t", assigned_at="now")
    ))
    assert isinstance(err, LineUnavailable)
    assert (err.code, err.params) == (code.LINE_TIDAK_MENJAWAB, {"line": line.name})


def test_line_that_refuses_carries_the_http_status():
    client, line = _line_client(lambda request: httpx.Response(409, text="busy"))
    err = _fails(lambda: asyncio.run(
        client.manual_reject(line, assignment_id="a", requested_by="op", requested_at="now")
    ))
    assert (err.code, err.params) == (code.LINE_MENOLAK, {"line": line.name, "status": 409})
