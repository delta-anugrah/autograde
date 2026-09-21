"""Konsol menyuruh satu line restart."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.integrations.notifications.line_client import LineClient, LineUnavailable


@pytest.fixture
def line():
    """Endpoint line pertama menurut Settings — `LineEndpoint` adalah
    NamedTuple, jadi field-nya harus cocok persis dan lebih aman diambil dari
    sumbernya daripada dirakit tangan."""
    return Settings().console_lines[0]


def test_restart_memanggil_endpoint(line):
    client = LineClient(Settings())
    with patch.object(client, "_post", new=AsyncMock()) as post:
        asyncio.run(client.restart(line))
    post.assert_awaited_once()
    assert post.await_args.args[1] == "/internal/restart"


def test_restart_melempar_saat_line_diam(line):
    client = LineClient(Settings())
    mati = LineUnavailable(LINE_TIDAK_MENJAWAB, "line tidak menjawab")
    with patch.object(client, "_post", new=AsyncMock(side_effect=mati)):
        with pytest.raises(LineUnavailable):
            asyncio.run(client.restart(line))
