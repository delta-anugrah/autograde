"""Konsol menjawab penugasan yang tersimpan untuk satu line.

Lawan `ConsoleStore` dan `ConsoleService` sungguhan, bukan teks sumber: yang
diuji di sini perilakunya — truk mana yang dijawab untuk mesin mana, dan apa yang
terjadi saat tidak ada truk. Jalur HTTP-nya diuji terpisah.

Ini sisi konsol dari perbaikan bug Lampung 2026-09-23: line yang restart lupa
truknya, layar tetap menampilkan platnya, dan janjang berikutnya tersimpan tanpa
`assignment_id`.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService


class FakeLine:
    async def assign_truck(self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None) -> None:
        return None


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())


def test_menjawab_truk_yang_sedang_dibongkar_di_line_itu(service):
    """Inti perbaikannya: line yang restart bisa mendapatkan truknya kembali."""
    line = service.lines[0]
    truk = service.register_manual_truck("B 1234 XY")
    asyncio.run(service.assign_truck(line.line_code, truk["id"]))

    jawaban = service.penugasan_untuk_mesin(line.machine_id)

    assert jawaban["truck_id"] == truk["id"]
    assert jawaban["assignment_id"]
    assert jawaban["plate"] == "B 1234 XY"


def test_line_lain_tidak_kebagian_truk_tetangga(service):
    """Konsol memegang penugasan tiga line. Menjawab tanpa memeriksa penanya akan
    membuat tonase satu truk mendarat di truk line sebelah."""
    line1, line2 = service.lines[0], service.lines[1]
    truk = service.register_manual_truck("B 1234 XY")
    asyncio.run(service.assign_truck(line1.line_code, truk["id"]))

    assert service.penugasan_untuk_mesin(line2.machine_id)["truck_id"] == ""


def test_truk_yang_sudah_lepas_tidak_dipasang_lagi(service):
    """Truk yang sudah pergi tidak boleh kembali menempel pada janjang berikutnya
    hanya karena line-nya kebetulan restart."""
    line = service.lines[0]
    truk = service.register_manual_truck("B 1234 XY")
    asyncio.run(service.assign_truck(line.line_code, truk["id"]))
    asyncio.run(service.release_truck(line.line_code))

    assert service.penugasan_untuk_mesin(line.machine_id)["truck_id"] == ""


def test_baris_setengah_jadi_tidak_dipasang(service):
    """Baris penugasan bisa punya `assignment_id` tanpa `truck_id` — truk yang
    dihapus, atau DB yang diedit tangan. Memasangnya memberi line truk hantu:
    `truck_folder` menamai folder capture dengan potongan kosong dan janjang satu
    truk menumpuk di folder yang bukan miliknya.

    Ditulis langsung ke store, bukan lewat `assign_truck`: jalur normal tidak bisa
    menghasilkan baris seperti ini, dan justru itu sebabnya penjaganya perlu diuji
    sendiri."""
    line = service.lines[0]
    service.store.set_assignment(line.line_code, "assignment-tanpa-truk", None)

    assert service.penugasan_untuk_mesin(line.machine_id)["truck_id"] == ""
    assert service.penugasan_untuk_mesin(line.machine_id)["assignment_id"] == ""


def test_mesin_tak_dikenal_dijawab_kosong_bukan_error(service):
    """Line yang belum terdaftar tetap harus bisa start. "Tidak ada truk" itu
    jawaban yang sah, bukan kegagalan."""
    assert service.penugasan_untuk_mesin("mesin-yang-tidak-ada")["truck_id"] == ""


def test_jam_penugasan_asli_yang_dipakai_bukan_jam_line_start(service):
    """Folder capture dinamai sekali per truk memakai jam ini. Menyegarkannya saat
    line restart akan memecah satu truk jadi dua folder di tengah pembongkaran."""
    line = service.lines[0]
    truk = service.register_manual_truck("B 1234 XY")
    asyncio.run(service.assign_truck(line.line_code, truk["id"]))

    jawaban = service.penugasan_untuk_mesin(line.machine_id)
    kartu = next(k for k in service.state()["lines"] if k["line_code"] == line.line_code)

    assert jawaban["assigned_at"] is not None
    assert jawaban["assignment_id"] == kartu["assignment"]["assignment_id"]
