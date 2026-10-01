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
# Firefox logs nothing for a failed response and Chromium words a 500 like the refused feed
# above, so a server error from the console is read from the response status instead.
_GALAT_SERVER = 500


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


class _Penjaga:
    """What a page did that it must not: reach beyond this machine, crash a script, or get a
    server error from the console."""

    def __init__(self, asal_konsol: str) -> None:
        self.asal_konsol = asal_konsol
        self.keluar: list[str] = []
        self.galat: list[str] = []

    def jaga(self, route) -> None:
        if urlsplit(route.request.url).hostname in _LOKAL:
            route.continue_()
        else:
            self.keluar.append(route.request.url)
            route.abort()

    def catat_console(self, pesan) -> None:
        if pesan.type == "error" and _BUKAN_GALAT not in pesan.text:
            self.galat.append(pesan.text)

    def catat_jawaban(self, jawaban) -> None:
        if jawaban.status >= _GALAT_SERVER and jawaban.url.startswith(self.asal_konsol):
            self.galat.append(f"{jawaban.status} from {jawaban.url}")

    def periksa(self) -> None:
        assert not self.keluar, f"the page reached beyond this machine: {self.keluar}"
        assert not self.galat, f"script or server errors on the page: {self.galat}"


_PENJAGA = pytest.StashKey[_Penjaga]()


@pytest.fixture
def halaman(request, page, konsol):
    """`page` on the console, guarded: nothing leaves this machine, no script crashes."""
    penjaga = _Penjaga(konsol.url)
    request.node.stash[_PENJAGA] = penjaga
    page.context.galat_uji = penjaga.galat  # read back only by the harness self-tests
    page.route("**/*", penjaga.jaga)
    page.on("pageerror", lambda exc: penjaga.galat.append(str(exc)))
    page.on("console", penjaga.catat_console)
    page.on("response", penjaga.catat_jawaban)
    page.goto(konsol.url + "/console")
    return page


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """The guard fails the test itself, not its teardown: pytest-playwright keeps the trace
    and the screenshot only for a test whose call failed."""
    hasil = yield
    penjaga = item.stash.get(_PENJAGA, None)
    if penjaga is not None:
        penjaga.periksa()
    return hasil
