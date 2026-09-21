"""Layar Support: baca daftar, simpan, restart line yang berubah.

Async lewat `asyncio.run`, bukan `pytest-asyncio` — pustaka itu tidak ada di
requirements CI (lihat `test_console_piston.py`, `test_console_lifespan.py`).
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.domain.sumber_kamera import SumberTidakSah
from palmgrade.integrations.notifications.line_client import LineUnavailable
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService


class FakeLine:
    """Line palsu — mencatat restart, atau menolak kalau `down`.

    Bentuknya mengikuti `FakeLine` di `test_console_piston.py`: kelas kecil,
    bukan `AsyncMock`, supaya tanda tangan yang salah ketahuan saat test jalan
    dan bukan diterima diam-diam.
    """

    def __init__(self, *, down: bool = False) -> None:
        self.restarted: list[str] = []
        self.down = down

    async def restart(self, line):
        if self.down:
            raise LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
        self.restarted.append(line.line_code)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """ConsoleService dengan media.env dan folder media di tmp_path."""
    media = tmp_path / "media"
    media.mkdir()
    (media / "konveyor.mp4").touch()
    (media / "sawit.jpg").touch()
    monkeypatch.setenv("MEDIA_DIR", str(media))
    monkeypatch.setenv("MEDIA_ENV_PATH", str(tmp_path / "media.env"))

    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    service = ConsoleService(settings, ConsoleStore(tmp_path / "console.db"), FakeLine())
    # Pembuktian berkas memakai cv2; unit suite berjalan tanpa cv2 dengan
    # sengaja, jadi dilewati di sini dan diuji sungguhan di e2e (Task 12).
    service._buktikan_berkas = lambda sumber, berkas: None  # type: ignore[method-assign]
    return service


def test_baca_memberi_bawaan_dan_daftar(svc):
    hasil = svc.sumber_kamera()
    assert hasil["lines"]["line-1"]["sumber"] == "hikrobot"
    assert hasil["video"] == ["konveyor.mp4"]
    assert hasil["foto"] == ["sawit.jpg"]


def test_simpan_menulis_dan_merestart_yang_berubah(svc):
    payload = {
        "line-1": {"sumber": "hikrobot"},
        "line-2": {"sumber": "video", "berkas": "konveyor.mp4", "ulang": True},
        "line-3": {"sumber": "hikrobot"},
    }
    hasil = asyncio.run(svc.simpan_sumber_kamera(payload, diubah_oleh="support@x"))

    # Hanya line-2 yang berubah dari bawaan.
    direstart = [b["line_code"] for b in hasil["lines"] if b["direstart"]]
    assert direstart == ["line-2"]
    assert svc.line_client.restarted == ["line-2"]
    assert svc.sumber_kamera()["lines"]["line-2"]["berkas"] == "konveyor.mp4"


def test_tidak_ada_yang_berubah_tidak_merestart(svc):
    payload = {kode: {"sumber": "hikrobot"} for kode in ("line-1", "line-2", "line-3")}
    hasil = asyncio.run(svc.simpan_sumber_kamera(payload, diubah_oleh="support@x"))
    assert svc.line_client.restarted == []
    assert all(not b["direstart"] for b in hasil["lines"])


def test_berkas_tidak_ada_ditolak_tanpa_menulis(svc):
    sebelum = svc.sumber_kamera()["lines"]
    with pytest.raises(SumberTidakSah, match="tidak ada di folder media"):
        asyncio.run(
            svc.simpan_sumber_kamera(
                {
                    "line-1": {"sumber": "video", "berkas": "hantu.mp4"},
                    "line-2": {"sumber": "hikrobot"},
                    "line-3": {"sumber": "hikrobot"},
                },
                diubah_oleh="support@x",
            )
        )
    assert svc.sumber_kamera()["lines"] == sebelum
    assert svc.line_client.restarted == []


def test_payload_cacat_ditolak_tanpa_menulis(svc):
    sebelum = svc.sumber_kamera()["lines"]
    with pytest.raises(SumberTidakSah):
        asyncio.run(
            svc.simpan_sumber_kamera(
                {
                    "line-1": {"sumber": "video", "berkas": ""},
                    "line-2": {"sumber": "hikrobot"},
                    "line-3": {"sumber": "hikrobot"},
                },
                diubah_oleh="support@x",
            )
        )
    assert svc.sumber_kamera()["lines"] == sebelum


def test_line_kurang_ditolak(svc):
    with pytest.raises(SumberTidakSah, match="line belum diisi"):
        asyncio.run(svc.simpan_sumber_kamera({"line-1": {"sumber": "hikrobot"}}, diubah_oleh="x"))


def test_line_asing_ditolak(svc):
    payload = {kode: {"sumber": "hikrobot"} for kode in ("line-1", "line-2", "line-3")}
    payload["line-9"] = {"sumber": "hikrobot"}
    with pytest.raises(SumberTidakSah, match="line tidak dikenal"):
        asyncio.run(svc.simpan_sumber_kamera(payload, diubah_oleh="x"))


def test_line_diam_tidak_membatalkan_simpan(svc):
    svc.line_client.down = True
    hasil = asyncio.run(
        svc.simpan_sumber_kamera(
            {
                "line-1": {"sumber": "hikrobot"},
                "line-2": {"sumber": "video", "berkas": "konveyor.mp4"},
                "line-3": {"sumber": "hikrobot"},
            },
            diubah_oleh="support@x",
        )
    )
    # Tersimpan, tapi dilaporkan belum direstart.
    assert svc.sumber_kamera()["lines"]["line-2"]["berkas"] == "konveyor.mp4"
    baris = next(b for b in hasil["lines"] if b["line_code"] == "line-2")
    assert baris["direstart"] is False
    assert "alasan" in baris
