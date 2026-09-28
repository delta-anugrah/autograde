"""Kunci konsol/line yang tidak sepakat (401/403) harus terlihat sebagai
PENOLAKAN, bukan "line tidak menjawab".

Sebelum perbaikan ini, `status()`, `health_detail()`, `plc_state()`, dan
`rekam_berkas()` memakai `raise_for_status()` di dalam `except httpx.HTTPError`,
jadi 401 (INTERNAL_SECRET beda antara konsol dan line) jatuh ke cabang yang sama
dengan koneksi putus: `LINE_TIDAK_MENJAWAB`. Di rollout campuran (compose host
pabrik cuma meneruskan `INTERNAL_SECRET` ke sebagian container) itu membuat
kartu line tampil OFFLINE padahal line masih menggrading dan masih mengirim
event lewat WEBHOOK_SECRET. `_post()` (dipakai assign/restart/dst) sudah benar
(`LINE_MENOLAK` + `status`); tes ini menuntut jalur baca ikut sama.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.operator_error import LINE_MENOLAK, LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineClient, LineUnavailable

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")


def _client(handler) -> LineClient:
    settings = Settings(console_line_host="http://line-host", internal_secret="rahasia")
    return LineClient(settings, transport=httpx.MockTransport(handler))


def _tolak_401(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, text="Invalid internal secret")


@pytest.mark.parametrize(
    "panggil",
    ["status", "health_detail", "plc_state", "rekam_berkas"],
)
def test_kunci_ditolak_bukan_line_tidak_menjawab(panggil):
    client = _client(_tolak_401)
    metode = getattr(client, panggil)
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(metode(LINE))
    assert info.value.code == LINE_MENOLAK
    assert info.value.code != LINE_TIDAK_MENJAWAB
    assert info.value.params.get("status") == 401


@pytest.mark.parametrize(
    "panggil",
    ["status", "health_detail", "plc_state", "rekam_berkas"],
)
def test_line_mati_sungguhan_tetap_line_tidak_menjawab(panggil):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client(handler)
    metode = getattr(client, panggil)
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(metode(LINE))
    assert info.value.code == LINE_TIDAK_MENJAWAB


def test_kunci_ditolak_menulis_warning(caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="palmgrade.integrations.notifications.line_client")
    client = _client(_tolak_401)
    with pytest.raises(LineUnavailable):
        asyncio.run(client.status(LINE))
    assert any("401" in r.message or "menolak" in r.message.lower() for r in caplog.records)
