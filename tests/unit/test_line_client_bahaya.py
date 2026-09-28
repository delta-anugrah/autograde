"""`LineClient` untuk Danger Zone — jaringan ditukar `httpx.MockTransport`.

Yang dijaga: alamat dan secret benar, penolakan line (409) sampai ke konsol
membawa kode statusnya (bukan diratakan jadi "line mati"), dan `hidup()` tidak
pernah melempar — dipanggil berulang saat menunggu line keluar.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.integrations.notifications.line_client import (
    LineClient,
    LinePlcTolak,
    LineUnavailable,
)

LINE = LineEndpoint("line-2", "Line 2", 8002, "m-2")


def _client(handler) -> LineClient:
    settings = Settings(console_line_host="http://line-host", internal_secret="rahasia")
    return LineClient(settings, transport=httpx.MockTransport(handler))


def _putus(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def test_hapus_data_mengirim_mode_dan_peminta():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["secret"] = request.headers.get("x-internal-secret")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "menghapus", "jeda_detik": 1.0})

    hasil = asyncio.run(_client(handler).hapus_data(LINE, mode="semua", diminta_oleh="s@pks.id"))

    assert seen["url"] == "http://line-host:8002/internal/hapus-data"
    assert seen["secret"] == "rahasia"
    assert seen["body"] == {"mode": "semua", "diminta_oleh": "s@pks.id"}
    assert hasil["status"] == "menghapus"


def test_hapus_data_ditolak_line_membawa_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": {"kode": "truk_terpasang"}})

    with pytest.raises(LinePlcTolak) as exc:
        asyncio.run(_client(handler).hapus_data(LINE, mode="transaksi", diminta_oleh="s"))
    assert exc.value.status_code == 409
    assert "truk_terpasang" in exc.value.detail


def test_hapus_data_line_putus():
    with pytest.raises(LineUnavailable):
        asyncio.run(_client(_putus).hapus_data(LINE, mode="transaksi", diminta_oleh="s"))


def test_rekam_hapus_dan_berkas():
    jalur: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        jalur.append((request.method, request.url.path))
        if request.url.path.endswith("/berkas"):
            return httpx.Response(200, json={"line_code": "line-2", "berkas": 3, "bytes": 99, "merekam": False})
        return httpx.Response(200, json={"line_code": "line-2", "berkas": 3, "bytes": 99})

    client = _client(handler)
    assert asyncio.run(client.rekam_berkas(LINE))["berkas"] == 3
    assert asyncio.run(client.rekam_hapus(LINE))["bytes"] == 99
    assert jalur == [("GET", "/internal/rekam/berkas"), ("POST", "/internal/rekam/hapus")]


def test_rekam_berkas_line_putus():
    with pytest.raises(LineUnavailable):
        asyncio.run(_client(_putus).rekam_berkas(LINE))


def test_hidup_benar_saat_health_menjawab():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    assert asyncio.run(_client(handler).hidup(LINE)) is True


@pytest.mark.parametrize(
    "handler",
    [
        _putus,
        lambda request: httpx.Response(503, text="starting"),
    ],
)
def test_hidup_salah_tanpa_melempar(handler):
    assert asyncio.run(_client(handler).hidup(LINE)) is False
