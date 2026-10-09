"""`GET /demo/<name>`: the bundled frames DEMO_MODE shows in the camera boxes (review focus 4)."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.routes.console import router as console_router

DEMO = Path(__file__).resolve().parents[2] / "src/palmgrade/static/demo"


@pytest.fixture
def console_client_factory(monkeypatch):
    """A console router app with the env set; `DEMO_MODE` is read per request (no cache)."""
    def buat(**env) -> TestClient:
        monkeypatch.delenv("DEMO_MODE", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        app = FastAPI()
        app.include_router(console_router)
        return TestClient(app)
    return buat


def test_manifest_lists_five_frames_and_every_file_exists():
    frames = json.loads((DEMO / "frames.json").read_text(encoding="utf-8"))["frames"]
    assert [f["src"] for f in frames] == [f"/demo/frame-{n}.webp" for n in range(1, 6)]
    for f in frames:
        assert (DEMO / f["src"].removeprefix("/demo/")).stat().st_size < 120_000
        assert set(f["kelas"]) <= {"Ripe", "Unripe", "JK", "TP"}


@pytest.mark.parametrize("nama", ["frame-1.webp", "frames.json"])
def test_served_only_in_demo_mode(console_client_factory, nama):
    assert console_client_factory(DEMO_MODE="1").get(f"/demo/{nama}").status_code == 200
    assert console_client_factory().get(f"/demo/{nama}").status_code == 404


@pytest.mark.parametrize("nama", ["..%2Fconsole.html", "frame-9.webp", "x.webp", "frame-1.webp.bak"])
def test_unknown_names_are_404(console_client_factory, nama):
    assert console_client_factory(DEMO_MODE="1").get(f"/demo/{nama}").status_code == 404
