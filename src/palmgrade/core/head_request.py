"""Serve HEAD through the GET route, on both apps (RFC 9110 §9.3.2).

FastAPI's `@get` routes accept GET only, so HEAD answered 405 and an uptime monitor
that checks with HEAD (UptimeRobot free cannot change its method) read the console
as down. One middleware instead of a HEAD on every route: the request reaches the
app as GET, so routing, auth and the licence guard see exactly what GET sees, and
the client gets the same status and headers with no body.

Pure ASGI, no torch or cv2: the console installs it too.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _BodyDone(Exception):
    """Raised into a response that keeps streaming after HEAD already has its answer."""


class HeadAsGetMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "HEAD":
            await self.app(scope, receive, send)
            return

        # A copy: the server keeps its own scope saying HEAD, which is what makes
        # uvicorn keep Content-Length and send no body bytes.
        scope = {**scope, "method": "GET"}
        body_sent = False

        async def send_without_body(message: Message) -> None:
            nonlocal body_sent
            if message["type"] != "http.response.body":
                await send(message)
                return
            if not body_sent:
                body_sent = True
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            # A file or an endless stream (the line's /video_feed MJPEG) would keep
            # producing for nobody; stop it at its next chunk.
            if message.get("more_body", False):
                raise _BodyDone

        try:
            await self.app(scope, receive, send_without_body)
        except _BodyDone:
            pass
