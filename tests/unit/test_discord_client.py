"""`DiscordClient` (batch 3.5) lawan `httpx.MockTransport`: tidak pernah memanggil Discord."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from palmgrade.integrations.notifications.discord_client import DiscordClient, DiscordTakTerjangkau

URL = "https://discord.com/api/webhooks/123/token-palsu-rahasia"


def _klien(handler) -> DiscordClient:
    return DiscordClient(URL, transport=httpx.MockTransport(handler))


def test_mengirim_isi_tanpa_mention_ke_alamat_webhook():
    diterima = []

    def handler(req: httpx.Request) -> httpx.Response:
        diterima.append((str(req.url), json.loads(req.content)))
        return httpx.Response(204)

    jawab = asyncio.run(_klien(handler).kirim("halo @everyone"))

    assert (jawab.status, jawab.retry_after) == (204, None)
    assert diterima == [(URL, {"content": "halo @everyone", "allowed_mentions": {"parse": []}})]


def test_retry_after_dari_badan_429():
    jawab = asyncio.run(_klien(lambda r: httpx.Response(429, json={"retry_after": 1.5})).kirim("x"))
    assert (jawab.status, jawab.retry_after) == (429, 1.5)


def test_retry_after_dari_header_kalau_badan_bukan_json():
    jawab = asyncio.run(_klien(lambda r: httpx.Response(429, text="lambat", headers={"Retry-After": "7"})).kirim("x"))
    assert jawab.retry_after == 7.0


def test_404_dipulangkan_apa_adanya():
    jawab = asyncio.run(_klien(lambda r: httpx.Response(404, json={"message": "Unknown Webhook"})).kirim("x"))
    assert (jawab.status, jawab.retry_after) == (404, None)


def test_jaringan_putus_tanpa_url_di_pesan():
    def handler(req):
        raise httpx.ConnectError(f"gagal konek ke {req.url}", request=req)

    with pytest.raises(DiscordTakTerjangkau) as info:
        asyncio.run(_klien(handler).kirim("x"))

    assert str(info.value) == "ConnectError"
    assert "token-palsu-rahasia" not in repr(info.value)
    assert info.value.__cause__ is None
