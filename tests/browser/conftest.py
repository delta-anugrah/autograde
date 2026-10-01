"""Fixtures for the browser suite: one isolated console, two fake lines, guarded pages.

Nothing here imports Playwright at module level: where it is missing, the test modules skip
themselves through `langkah.py` (or fail in CI), and these fixtures are never reached.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from harness import KonsolUji, port_bebas
from line_palsu import LinePalsu

_LOKAL = {"127.0.0.1", "localhost"}
# What Chromium logs for the offline line's camera feed and for a deliberate 4xx answer.
# Anything else on the console, and every uncaught exception, fails the test.
_BUKAN_GALAT = "Failed to load resource"


@pytest.fixture(scope="session")
def lines():
    """line-1 and line-2 answer; line-3 is a port nobody listens on, an offline line."""
    hidup = {"line-1": LinePalsu.mulai("line-1"), "line-2": LinePalsu.mulai("line-2")}
    try:
        yield {**hidup, "port-line-3": port_bebas()}
    finally:
        for line in hidup.values():
            line.berhenti()


@pytest.fixture(scope="session")
def konsol(tmp_path_factory, lines):
    k = KonsolUji(
        tmp_path_factory.mktemp("konsol"),
        port_line=(lines["line-1"].port, lines["line-2"].port, lines["port-line-3"]),
    )
    k.seed(hari=10)
    k.mulai()
    try:
        yield k
    finally:
        k.berhenti()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "locale": "id-ID",
        "timezone_id": "Asia/Jakarta",
        "viewport": {"width": 1920, "height": 1080},
        "accept_downloads": True,
    }


@pytest.fixture
def halaman(page, konsol):
    """`page` on the console, guarded: nothing leaves this machine, no script crashes."""
    keluar: list[str] = []
    galat: list[str] = []
    page.context.galat_uji = galat  # read back only by the harness self-test

    def jaga(route) -> None:
        if urlsplit(route.request.url).hostname in _LOKAL:
            route.continue_()
        else:
            keluar.append(route.request.url)
            route.abort()

    def catat_console(pesan) -> None:
        if pesan.type == "error" and _BUKAN_GALAT not in pesan.text:
            galat.append(pesan.text)

    page.route("**/*", jaga)
    page.on("pageerror", lambda exc: galat.append(str(exc)))
    page.on("console", catat_console)
    page.goto(konsol.url + "/console")
    yield page
    assert not keluar, f"the page reached beyond this machine: {keluar}"
    assert not galat, f"script errors on the page: {galat}"
