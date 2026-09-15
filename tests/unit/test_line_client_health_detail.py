"""`LineClient.health_detail()` — the support diagnostics screen's read from a line.

Same shape as `test_erp_client.py`: `httpx.MockTransport` swaps the network,
never a real socket.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.integrations.notifications.line_client import LineClient, LineUnavailable

LINE = LineEndpoint("line-1", "Line 1", 8001, "m-1")


def _client(handler) -> LineClient:
    settings = Settings(console_line_host="http://line-host", internal_secret="rahasia")
    return LineClient(settings, transport=httpx.MockTransport(handler))


def test_health_detail_hits_the_right_path_and_host():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["secret"] = request.headers.get("x-internal-secret")
        return httpx.Response(200, json={"status": "ok"})

    result = asyncio.run(_client(handler).health_detail(LINE))

    assert seen["url"] == "http://line-host:8001/health/detail"
    assert seen["secret"] == "rahasia"
    assert result == {"status": "ok"}


def test_health_detail_returns_the_full_body():
    body = {
        "status": "ok",
        "camera_connected": True,
        "gpu_available": True,
        "workers": [{"name": "capture", "alive": True}],
        "plc": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    assert asyncio.run(_client(handler).health_detail(LINE)) == body


def test_health_detail_raises_line_unavailable_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(LineUnavailable):
        asyncio.run(_client(handler).health_detail(LINE))


def test_health_detail_raises_line_unavailable_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    with pytest.raises(LineUnavailable):
        asyncio.run(_client(handler).health_detail(LINE))
