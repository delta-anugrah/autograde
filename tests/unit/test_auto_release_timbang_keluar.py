"""Truk yang sudah timbang keluar tidak boleh tetap memegang line (G5).

Kalau `Release` terlewat, line masih menganggap truk itu aktif dan janjang truk
BERIKUTNYA dihitung ke truk yang sudah pulang — tonase yang dibayar ke petani,
mendarat di baris yang salah, tanpa apa pun di layar yang mengatakannya. Timeout
6 jam di AutoERP tetap memfinalisasi tiketnya, jadi kegagalannya tidak pernah
terlihat sebagai kegagalan: angkanya saja yang salah.

Yang dikunci di sini: timbang keluar melepas SEMUA line yang memegang truk itu,
meninggalkan jejak yang bisa dilihat operator, dan tidak menyentuh line truk lain.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService


class FakeLine:
    def __init__(self) -> None:
        self.kiriman: list[dict] = []

    async def assign_truck(
        self, line, *, assignment_id, truck_id, assigned_at, ffb_source=None, plate=None
    ):
        self.kiriman.append({"line": line.line_code, "truck_id": truck_id})

    def pelepasan(self) -> list[dict]:
        """Kiriman yang MELEPAS line (truck_id kosong), bukan yang memasang."""
        return [k for k in self.kiriman if not k["truck_id"]]


@pytest.fixture
def service(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    return ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())


def _timbang(**over):
    payload = {
        "plate_number": "B 1234 XY",
        "entered_at": "2026-09-21T01:30:00+00:00",
        "gross_kg": 12500,
    }
    payload.update(over)
    return payload


def _keluar(**over):
    return _timbang(tare_kg=5000, exited_at="2026-09-21T03:00:00+00:00", **over)


def _pasang(service, line_code, plate):
    truck = service.register_manual_truck(plate)
    asyncio.run(service.assign_truck(line_code, truck["id"]))
    return truck


def _dipegang(service) -> dict[str, str]:
    return {c: a["truck_id"] for c, a in service.store.assignments().items() if a.get("truck_id")}


# ── inti G5 ─────────────────────────────────────────────────────────────


def test_timbang_keluar_melepas_line_yang_memegang_truk(service):
    _pasang(service, "line-1", "B 1234 XY")
    assert _dipegang(service)

    asyncio.run(service.record_weighing(_keluar()))

    assert _dipegang(service) == {}, (
        "line masih memegang truk yang sudah pulang — janjang berikutnya salah alamat"
    )
    assert len(service.line_client.pelepasan()) == 1, (
        "line tidak diberi tahu, jadi dia masih menstempel truk itu"
    )


def test_truk_dibongkar_di_tiga_line_dilepas_semuanya(service):
    """Satu truk boleh dibongkar paralel — `assignments` berkunci line, bukan truk."""
    truck = service.register_manual_truck("B 1234 XY")
    for line_code in ("line-1", "line-2", "line-3"):
        asyncio.run(service.assign_truck(line_code, truck["id"]))

    asyncio.run(service.record_weighing(_keluar()))

    assert _dipegang(service) == {}, "satu line terlewat: tonasenya mendarat di truk yang salah"


def test_line_truk_lain_tidak_ikut_dilepas(service):
    """Melepas berdasarkan truk, bukan menyapu semua line."""
    _pasang(service, "line-1", "B 1234 XY")
    lain = _pasang(service, "line-2", "B 9999 ZZ")

    asyncio.run(service.record_weighing(_keluar()))

    assert _dipegang(service) == {"line-2": lain["id"]}, (
        "truk lain ikut terlepas — bongkarannya berhenti dihitung di tengah jalan"
    )


# ── yang TIDAK boleh melepas ────────────────────────────────────────────


def test_timbang_masuk_tidak_melepas(service):
    """Bruto saja = truk baru datang. Melepas di sini menghentikan bongkaran."""
    truck = _pasang(service, "line-1", "B 1234 XY")

    asyncio.run(service.record_weighing(_timbang()))  # tanpa tare, tanpa exited_at

    assert _dipegang(service) == {"line-1": truck["id"]}, "truk yang baru masuk ikut dilepas"


def test_truk_tanpa_assignment_tidak_meledak(service):
    """Jalur biasa: operator sudah menekan Release sendiri sebelum timbang keluar."""
    asyncio.run(service.record_weighing(_keluar()))
    assert service.line_client.pelepasan() == []


# ── jejak yang dilihat operator ─────────────────────────────────────────


def test_pelepasan_otomatis_meninggalkan_jejak(service):
    """Pelepasan senyap menukar satu kegagalan diam dengan kegagalan diam lain.

    Operator yang menimbang keluar terlalu cepat (antrean jembatan timbang, bongkar
    belum habis) harus tahu line-nya baru saja lepas, supaya bisa meng-assign ulang.
    """
    _pasang(service, "line-1", "B 1234 XY")

    asyncio.run(service.record_weighing(_keluar()))

    jejak = service.store.auto_releases_terbaru()
    assert len(jejak) == 1
    assert jejak[0]["line_code"] == "line-1"
    assert jejak[0]["plate_number"] == "B 1234 XY"


def test_jejak_tidak_ditulis_kalau_operator_sudah_release(service):
    """Peringatan yang muncul tanpa sebab mengajari operator mengabaikannya."""
    _pasang(service, "line-1", "B 1234 XY")
    asyncio.run(service.release_truck("line-1"))

    asyncio.run(service.record_weighing(_keluar()))

    assert service.store.auto_releases_terbaru() == []


def test_state_membawa_pelepasan_ke_layar(service):
    """Jejak yang tidak sampai ke `state()` sama saja tidak ada: layar tidak membacanya."""
    _pasang(service, "line-1", "B 1234 XY")
    asyncio.run(service.record_weighing(_keluar()))

    assert len(service.state()["auto_releases"]) == 1
