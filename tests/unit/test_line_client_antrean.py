"""LineClient ke `/internal/outbox*` (batch 2.4): kunci yang ditolak = LINE_MENOLAK, bukan "tidak menjawab"."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineClient, LineUnavailable

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")


def _klien(handler) -> LineClient:
    return LineClient(
        replace(Settings(), console_line_host="http://line", internal_secret="kunci-palsu"),
        transport=httpx.MockTransport(handler),
    )


def _mati(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("mati", request=request)


def test_ringkasan_memanggil_lane_dengan_kunci():
    dilihat: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        dilihat.append(request)
        return httpx.Response(200, json={"menunggu": 3})

    assert asyncio.run(_klien(handler).antrean_line(LINE)) == {"menunggu": 3}
    assert (dilihat[0].method, str(dilihat[0].url)) == ("GET", "http://line:8001/internal/outbox")
    assert dilihat[0].headers["x-internal-secret"] == "kunci-palsu"


@pytest.mark.parametrize("status", [401, 403])
def test_ringkasan_kunci_ditolak(status):
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(_klien(lambda r: httpx.Response(status, text="Invalid internal secret")).antrean_line(LINE))
    assert (info.value.code, info.value.params["status"]) == (LINE_MENOLAK, status)


def test_ringkasan_line_mati():
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(_klien(_mati).antrean_line(LINE))
    assert info.value.code == LINE_TIDAK_MENJAWAB


def test_kirim_ulang_mengembalikan_jumlah():
    dilihat: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        dilihat.append(request)
        return httpx.Response(200, json={"requeued": 7})

    assert asyncio.run(_klien(handler).kirim_ulang_antrean_line(LINE)) == 7
    assert (dilihat[0].method, dilihat[0].url.path) == ("POST", "/internal/outbox/requeue")
    assert dilihat[0].headers["x-internal-secret"] == "kunci-palsu"


@pytest.mark.parametrize("status", [401, 403, 500])
def test_kirim_ulang_ditolak_line_menolak_membawa_status(status):
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(_klien(lambda r: httpx.Response(status, text="tolak")).kirim_ulang_antrean_line(LINE))
    assert (info.value.code, info.value.params["status"]) == (LINE_MENOLAK, status)


def test_kirim_ulang_line_mati():
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(_klien(_mati).kirim_ulang_antrean_line(LINE))
    assert info.value.code == LINE_TIDAK_MENJAWAB
