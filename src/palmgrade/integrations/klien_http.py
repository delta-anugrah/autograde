"""One `httpx.AsyncClient` kept for many calls (batch 6.5).

`LineClient` and `ErpClient` used to open a client per call. Each one built a new TLS
context (the CA bundle read again) on the console's event loop, and no connection was ever
reused: three times a second for the line status alone.

Two things a kept client would change are switched off here, so a call behaves exactly as it
did with a client of its own:

* cookies: a kept client would send back whatever a server set (`sid=Guest` from Frappe)
  beside the token. The jar below never stores one.
* the event loop: a client's connections belong to the loop that opened them. The console
  has one loop for its whole life, but `asyncio.run` in a test or a script makes a new one
  per call, so a client made in another loop is dropped and a new one is built.
"""
from __future__ import annotations

import asyncio
from http.cookiejar import CookieJar
from typing import Any

import httpx


class _TanpaKue(CookieJar):
    """A cookie jar that keeps nothing."""

    def extract_cookies(self, response: Any, request: Any) -> None:
        return None

    def set_cookie(self, cookie: Any) -> None:
        return None


class KlienBersama:
    """Hands out one `httpx.AsyncClient`, built on first use with `argumen`."""

    def __init__(self, **argumen: Any) -> None:
        self._argumen = argumen
        self._klien: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def ambil(self) -> httpx.AsyncClient:
        """The kept client. Call it from a coroutine, once per request."""
        loop = asyncio.get_running_loop()
        if self._klien is None or self._klien.is_closed or self._loop is not loop:
            # A client left behind by a closed loop cannot be closed from this one; it holds
            # no socket the console still uses, so it is simply dropped.
            self._klien = httpx.AsyncClient(cookies=_TanpaKue(), **self._argumen)
            self._loop = loop
        return self._klien

    async def tutup(self) -> None:
        """Close the kept client, if any. The next `ambil()` builds a new one."""
        klien, self._klien = self._klien, None
        if klien is not None and not klien.is_closed and self._loop is asyncio.get_running_loop():
            await klien.aclose()
