"""Automatic line assignment respects an Update now install (rules 36 and 38).

Manual Tugaskan goes through `PembaruanService.menugaskan(line)`: refused while an install
runs, and counted while the line has not answered, so the install refuses to start. The
automatic paths (after a weigh-in, after Lepas, "Tugaskan sekarang") assign too, and used to
skip that lock: a truck weighed in during an install could land on a line that was about to
restart. Found while cutting the release after #214 (2026-10-03).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from test_penugasan_line_otomatis import FakeLine, _buat, _isi, _kosong, _nyalakan, _plat_di_line

from palmgrade.domain.pembaruan import PembaruanBerjalan
from palmgrade.domain.plate import truck_id_for


class PenjagaPalsu:
    """The two members of `PembaruanService` the console service uses."""

    def __init__(self) -> None:
        self.berjalan = False
        self.dimasuki: list[str] = []

    def sedang_berjalan(self) -> bool:
        return self.berjalan

    @asynccontextmanager
    async def menugaskan(self, line_code: str):
        if self.berjalan:
            raise PembaruanBerjalan()
        self.dimasuki.append(line_code)
        yield


@pytest.fixture
def service(tmp_path: Path):
    service = _buat(tmp_path, FakeLine())
    service.pakai_penjaga_pembaruan(PenjagaPalsu())
    _nyalakan(service)
    return service


def test_timbang_isi_selama_pembaruan_tidak_memasang_dan_truk_menunggu(service):
    service._penjaga_pembaruan.berjalan = True
    row = _isi(service, "BE 1 AA")
    assert row["dipasang"] == []
    assert _plat_di_line(service) == set()
    assert [a["plate_number"] for a in service.antrean_bongkar()] == ["BE 1 AA"]


def test_tugaskan_sekarang_selama_pembaruan_ditolak_tanpa_memasang(service):
    service._penjaga_pembaruan.berjalan = True
    _isi(service, "BE 1 AA")
    wid = service.antrean_bongkar()[0]["weighing_id"]
    with pytest.raises(PembaruanBerjalan):
        asyncio.run(service.pasang_dari_antrean(wid))
    assert _plat_di_line(service) == set()


def test_penugasan_otomatis_lewat_kunci_pembaruan_per_line(service):
    """Counted per line, so an install that starts meanwhile sees the assign in flight."""
    _isi(service, "BE 1 AA")
    assert service._penjaga_pembaruan.dimasuki == ["line-1", "line-2", "line-3"]
    assert _plat_di_line(service) == {"BE 1 AA"}


def test_sesudah_pembaruan_truk_yang_menunggu_naik_lagi(service):
    service._penjaga_pembaruan.berjalan = True
    _isi(service, "BE 1 AA")
    service._penjaga_pembaruan.berjalan = False
    row = _isi(service, "BE 2 BB", 10)
    # The older truck goes first, as always; the newer one waits behind it.
    assert {d["plate_number"] for d in row["dipasang"] if d["terpasang"]} == {"BE 1 AA"}
    assert _plat_di_line(service) == {"BE 1 AA"}


def test_timbang_kosong_selama_pembaruan_melepas_tapi_tidak_memasang_berikutnya(service):
    _isi(service, "BE 1 AA")
    _isi(service, "BE 2 BB", 10)
    service._penjaga_pembaruan.berjalan = True
    row = _kosong(service, "BE 1 AA")
    assert row["dipasang"] == []
    assert _plat_di_line(service) == set()
    assert [a["plate_number"] for a in service.antrean_bongkar()] == ["BE 2 BB"]


def test_tanpa_penjaga_tetap_jalan_seperti_sebelumnya(tmp_path: Path):
    """Route tests and tools build a ConsoleService without the Update now service."""
    service = _buat(tmp_path, FakeLine())
    _nyalakan(service)
    _isi(service, "BE 1 AA")
    assert truck_id_for("BE 1 AA") in {a["truck_id"] for a in service.store.assignments().values()}
