"""HEAD answers like GET without a body (RFC 9110 §9.3.2).

An uptime monitor that checks with HEAD (UptimeRobot free cannot change its method)
read the console as down: FastAPI routes declared with `@get` answered 405. The
middleware serves HEAD through the GET route, so status and headers match GET.

The app is assembled here, never `create_console_app()` (T2); the wiring into both
real apps is checked on their source.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.testclient import TestClient

from palmgrade.core.head_request import HeadAsGetMiddleware

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"


def _app(tmp_path: Path) -> FastAPI:
    halaman = tmp_path / "console.html"
    halaman.write_text("<html>console</html>")
    app = FastAPI()
    app.add_middleware(HeadAsGetMiddleware)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse("/console")

    @app.get("/console")
    async def console() -> FileResponse:
        return FileResponse(halaman, media_type="text/html")

    @app.get("/video_feed")
    async def video_feed() -> StreamingResponse:
        async def tanpa_henti():
            while True:
                yield b"--frame\r\n"
                await asyncio.sleep(0)

        return StreamingResponse(tanpa_henti(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.post("/hanya-post")
    async def hanya_post() -> dict:
        return {"ok": True}

    return app


def test_head_root_and_health_answer_200_with_no_body(tmp_path):
    client = TestClient(_app(tmp_path))
    for path in ("/", "/health"):
        r = client.head(path)
        assert r.status_code == 200, path
        assert r.content == b"", path


def test_head_carries_the_same_headers_as_get(tmp_path):
    client = TestClient(_app(tmp_path))
    for path in ("/health", "/console"):
        get, head = client.get(path), client.head(path)
        assert head.headers["content-type"] == get.headers["content-type"], path
        assert head.headers["content-length"] == get.headers["content-length"], path


def test_head_root_is_the_same_redirect_as_get(tmp_path):
    client = TestClient(_app(tmp_path), follow_redirects=False)
    get, head = client.get("/"), client.head("/")
    assert head.status_code == get.status_code == 307
    assert head.headers["location"] == get.headers["location"] == "/console"


def test_get_is_unchanged(tmp_path):
    client = TestClient(_app(tmp_path))
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/")
    assert r.status_code == 200
    assert r.text == "<html>console</html>"


def test_post_to_a_get_only_route_stays_405(tmp_path):
    client = TestClient(_app(tmp_path))
    r = client.post("/health")
    assert r.status_code == 405
    assert r.headers["allow"] == "GET"


def test_head_to_a_post_only_route_stays_405(tmp_path):
    assert TestClient(_app(tmp_path)).head("/hanya-post").status_code == 405


def test_head_on_an_endless_stream_returns_instead_of_hanging(tmp_path):
    r = TestClient(_app(tmp_path)).head("/video_feed")
    assert r.status_code == 200
    assert r.content == b""


def test_both_real_apps_install_the_middleware():
    for nama in ("console_main.py", "main.py"):
        assert "app.add_middleware(HeadAsGetMiddleware)" in (SRC / nama).read_text(), nama
