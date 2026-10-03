"""The console asks a line to reconnect its camera: every answer becomes a code the screen words."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import (
    KAMERA_TANPA_SAMBUNG_ULANG,
    LINE_MENOLAK,
    LINE_TIDAK_MENJAWAB,
)
from palmgrade.integrations.notifications import line_client
from palmgrade.integrations.notifications.line_client import (
    KameraTanpaSambungUlang,
    LineClient,
    LineUnavailable,
)

SECRET = "kunci-sambung-ulang"


def _klien(jawab) -> tuple[LineClient, list[httpx.Request]]:
    diterima: list[httpx.Request] = []

    def penangan(request: httpx.Request) -> httpx.Response:
        diterima.append(request)
        return jawab(request)

    settings = replace(Settings(), console_line_host="http://line", internal_secret=SECRET)
    return LineClient(settings, transport=httpx.MockTransport(penangan)), diterima


@pytest.fixture
def line():
    return Settings().console_lines[0]


def test_accepted_sends_who_asked_with_the_secret(line):
    klien, diterima = _klien(lambda _r: httpx.Response(202, json={"status": "requested"}))
    asyncio.run(klien.reconnect_camera(line, requested_by="Pak Budi"))
    (req,) = diterima
    assert req.url.path == "/internal/camera/reconnect"
    assert req.url.port == line.port
    assert req.headers["x-internal-secret"] == SECRET
    assert json.loads(req.read()) == {"requested_by": "Pak Budi"}


def test_a_source_without_a_camera_reaches_the_screen_as_its_own_code(line):
    klien, _ = _klien(lambda _r: httpx.Response(
        409, json={"detail": {"kode": "kamera_tanpa_sambung_ulang", "pesan": "bukan kamera"}}
    ))
    with pytest.raises(KameraTanpaSambungUlang) as info:
        asyncio.run(klien.reconnect_camera(line, requested_by="Pak Budi"))
    assert info.value.code == KAMERA_TANPA_SAMBUNG_ULANG
    assert info.value.params["line"] == line.name


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_key_is_line_menolak(line, status):
    klien, _ = _klien(lambda _r: httpx.Response(status, json={"detail": "Invalid internal secret"}))
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(klien.reconnect_camera(line, requested_by="Pak Budi"))
    assert info.value.code == LINE_MENOLAK


@pytest.mark.parametrize("status", [404, 409, 500])
def test_any_other_refusal_is_line_tidak_menjawab(line, status):
    """404 = an older line image without the route; a 409 without the code is not ours."""
    klien, _ = _klien(lambda _r: httpx.Response(status, json={"detail": "x"}))
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(klien.reconnect_camera(line, requested_by="Pak Budi"))
    assert info.value.code == LINE_TIDAK_MENJAWAB
    assert info.value.params["status"] == status


def test_a_line_that_does_not_answer_is_line_tidak_menjawab(line):
    def mati(request):
        raise httpx.ConnectError("refused", request=request)

    klien, _ = _klien(mati)
    with pytest.raises(LineUnavailable) as info:
        asyncio.run(klien.reconnect_camera(line, requested_by="Pak Budi"))
    assert info.value.code == LINE_TIDAK_MENJAWAB


def test_the_timeout_is_a_short_named_constant():
    """The line answers before it reconnects, so the button never waits on the camera."""
    assert 0 < line_client.TIMEOUT_SAMBUNG_ULANG_S <= 5.0
