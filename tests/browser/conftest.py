"""Fixtures for the browser suite: one isolated console, two fake lines, guarded pages.

Nothing here imports Playwright at module level: where it is missing, the test modules skip
themselves through `langkah.py` (or fail in CI), and these fixtures are never reached. The
Playwright names below are for type hints only.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import pytest
from harness import KonsolUji, port_bebas
from line_palsu import LinePalsu

if TYPE_CHECKING:
    from playwright.sync_api import ConsoleMessage, Page, Response, Route

_LOKAL = {"127.0.0.1", "localhost"}
# What Chromium logs for the offline line's camera feed and for a deliberate 4xx answer.
# Anything else on the console, and every uncaught exception, fails the test. A 4xx passes
# this filter on purpose: the screen answers 401 before sign-in and words refusals from
# their codes. Two kinds are read from the response status instead, below.
_BUKAN_GALAT = "Failed to load resource"
# Firefox logs nothing for a failed response and Chromium words a 500 like the refused feed
# above, so a server error from the console is read from the response status.
_GALAT_SERVER = 500
# The same for a 404 on the console's own API whose body is not a worded refusal: the screen
# asking for a path the server does not have (a renamed route, FastAPI's "Not Found"). The
# console's deliberate 404 (unknown line or truck) carries a code the screen words.
_TIDAK_ADA = 404
_API_KONSOL = "/api/"
# An existing console path called with the wrong method: as broken, and as quiet in Firefox.
_METODE_SALAH = 405


@pytest.fixture(scope="session")
def lines() -> Iterator[dict[str, Any]]:
    """line-1 and line-2 answer; line-3 is a port nobody listens on, an offline line.

    The port is picked and released, not held: a socket bound without listening is refused
    at once on Linux but left to time out on macOS, which is not how a stopped line behaves.
    """
    hidup = {"line-1": LinePalsu.mulai("line-1"), "line-2": LinePalsu.mulai("line-2")}
    try:
        yield {**hidup, "port-line-3": port_bebas()}
    finally:
        for line in hidup.values():
            line.berhenti()


@pytest.fixture(scope="session")
def konsol(tmp_path_factory: pytest.TempPathFactory, lines: dict[str, Any]) -> Iterator[KonsolUji]:
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
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    return {
        **browser_context_args,
        "locale": "id-ID",
        "timezone_id": "Asia/Jakarta",
        "viewport": {"width": 1920, "height": 1080},
        "accept_downloads": True,
    }


class _Penjaga:
    """What a page did that it must not: reach beyond this machine, crash a script, get a
    server error from the console, or ask the console for an API path it does not have."""

    def __init__(self, asal_konsol: str) -> None:
        self.asal_konsol = asal_konsol
        self.keluar: list[str] = []
        self.galat: list[str] = []
        # Judged in `temuan`, after the test: a body is not read inside the event callback. A
        # test that navigates away would lose these bodies in Chromium and fail as "no code";
        # none does today.
        self._hilang: list[Response] = []

    def jaga(self, route: Route) -> None:
        if urlsplit(route.request.url).hostname in _LOKAL:
            route.continue_()
        else:
            self.keluar.append(route.request.url)
            route.abort()

    def catat_console(self, pesan: ConsoleMessage) -> None:
        if pesan.type == "error" and _BUKAN_GALAT not in pesan.text:
            self.galat.append(pesan.text)

    def catat_galat_skrip(self, galat: Exception) -> None:
        self.galat.append(str(galat))

    def catat_jawaban(self, jawaban: Response) -> None:
        if not jawaban.url.startswith(self.asal_konsol):
            return
        if jawaban.status >= _GALAT_SERVER or jawaban.status == _METODE_SALAH:
            self.galat.append(f"{jawaban.status} from {jawaban.url}")
        elif jawaban.status == _TIDAK_ADA and urlsplit(jawaban.url).path.startswith(_API_KONSOL):
            self._hilang.append(jawaban)

    def _rute_hilang(self) -> list[str]:
        from playwright.sync_api import Error as GalatPlaywright

        hilang = []
        for jawaban in self._hilang:
            try:
                detail = jawaban.json().get("detail")
            except (GalatPlaywright, ValueError):
                detail = None  # no JSON body: not the console's worded refusal either
            if not (isinstance(detail, dict) and "code" in detail):
                hilang.append(f"{jawaban.status} from {jawaban.url} (no such route, or a refusal without a code)")
        return hilang

    def temuan(self) -> list[str]:
        return self.galat + self._rute_hilang()

    def bersihkan(self) -> None:
        self.galat.clear()
        self._hilang.clear()

    def periksa(self) -> None:
        assert not self.keluar, f"the page reached beyond this machine: {self.keluar}"
        temuan = self.temuan()
        assert not temuan, f"script or server errors on the page: {temuan}"


_PENJAGA = pytest.StashKey[_Penjaga]()


@pytest.fixture
def halaman(request: pytest.FixtureRequest, page: Page, konsol: KonsolUji) -> Page:
    """`page` on the console, guarded: nothing leaves this machine, no script crashes."""
    penjaga = _Penjaga(konsol.url)
    request.node.stash[_PENJAGA] = penjaga
    # Read back only by the harness self-tests.
    page.context.galat_uji = penjaga.galat
    page.context.penjaga_uji = penjaga
    page.route("**/*", penjaga.jaga)
    page.on("pageerror", penjaga.catat_galat_skrip)
    page.on("console", penjaga.catat_console)
    page.on("response", penjaga.catat_jawaban)
    page.goto(konsol.url + "/console")
    return page


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    """The guard fails the test itself, not its teardown: pytest-playwright keeps the trace
    and the screenshot only for a test whose call failed."""
    hasil = yield
    penjaga = item.stash.get(_PENJAGA, None)
    if penjaga is not None:
        penjaga.periksa()
    return hasil
