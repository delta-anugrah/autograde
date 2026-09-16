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
from palmgrade.domain import operator_error as kode
from palmgrade.domain.operator_error import InvalidInput, OperatorError
from palmgrade.integrations.notifications.line_client import LineClient, LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import MINIMUM_BERAT_KG, ConsoleService


class DiamLine:
    async def assign_truck(self, *_a, **_kw) -> None:
        return None


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), DiamLine())


def _timbang(service, **isi):
    return service.catat_timbangan(
        {"plate_number": "B 1234 XY", "ref": "T-1", "entered_at": "2026-09-14T08:00:00+07:00", **isi}
    )


def _gagal(fungsi) -> OperatorError:
    with pytest.raises(OperatorError) as tangkap:
        fungsi()
    return tangkap.value


def test_line_tak_dikenal_membawa_kode_dan_nama_line(service):
    err = _gagal(lambda: asyncio.run(service.assign_truck("line-9", "t")))
    assert (err.code, err.params) == (kode.LINE_TIDAK_DIKENAL, {"line": "line-9"})
    assert isinstance(err, ValueError)  # the route still answers 404


def test_plat_kosong_membawa_kode(service):
    err = _gagal(lambda: service.daftar_truk_manual("  "))
    assert err.code == kode.PLAT_KOSONG
    assert isinstance(err, ValueError)


def test_bruto_bukan_angka_menyebut_kolom_dan_isinya(service):
    err = _gagal(lambda: _timbang(service, gross_kg="abc"))
    assert (err.code, err.params) == (kode.BUKAN_ANGKA, {"field": "gross_kg", "value": "abc"})


def test_berat_negatif_menyebut_kolomnya(service):
    err = _gagal(lambda: _timbang(service, gross_kg="-5"))
    assert (err.code, err.params) == (kode.NEGATIF, {"field": "gross_kg", "value": -5.0})


def test_berat_di_bawah_minimum_membawa_angka_bukan_teks(service):
    # Numbers, not strings: the screen formats them with the operator's decimal mark.
    err = _gagal(lambda: _timbang(service, gross_kg="14,82"))
    assert err.code == kode.DI_BAWAH_MINIMUM
    assert err.params == {"field": "gross_kg", "value": 14.82, "minimum": MINIMUM_BERAT_KG}


def test_tara_lebih_besar_dari_bruto_membawa_keduanya(service):
    _timbang(service, gross_kg="14000")
    err = _gagal(lambda: _timbang(service, tare_kg="15000", exited_at="2026-09-14T09:00:00+07:00"))
    assert (err.code, err.params) == (kode.TARA_LEBIH_BESAR, {"tara": 15000.0, "bruto": 14000.0})


def test_pesan_lama_tetap_ada_untuk_log_dan_program_timbangan(service):
    err = _gagal(lambda: _timbang(service, gross_kg="abc"))
    assert str(err) == "gross_kg bukan angka: 'abc'"


def test_detail_membawa_kode_parameter_dan_pesan():
    err = InvalidInput(kode.PLAT_KOSONG, "nomor polisi tidak boleh kosong")
    assert err.as_detail() == {
        "code": "plat_kosong",
        "params": {},
        "message": "nomor polisi tidak boleh kosong",
    }


def _line_client(handler) -> tuple[LineClient, object]:
    settings = Settings()
    return LineClient(settings, transport=httpx.MockTransport(handler)), settings.console_lines[0]


def test_line_yang_tidak_menjawab_membawa_kode_dan_nama_line():
    def putus(request):
        raise httpx.ConnectError("All connection attempts failed", request=request)

    client, line = _line_client(putus)
    err = _gagal(lambda: asyncio.run(
        client.assign_truck(line, assignment_id="a", truck_id="t", assigned_at="now")
    ))
    assert isinstance(err, LineUnavailable)
    assert (err.code, err.params) == (kode.LINE_TIDAK_MENJAWAB, {"line": line.name})


def test_line_yang_menolak_membawa_status_http():
    client, line = _line_client(lambda request: httpx.Response(409, text="busy"))
    err = _gagal(lambda: asyncio.run(
        client.manual_reject(line, assignment_id="a", requested_by="op", requested_at="now")
    ))
    assert (err.code, err.params) == (kode.LINE_MENOLAK, {"line": line.name, "status": 409})
