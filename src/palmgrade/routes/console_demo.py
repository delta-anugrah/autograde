"""`GET /demo/<name>`: the bundled frames DEMO_MODE shows in the camera boxes. 404 elsewhere.

Only on demo-autograde.smagri.id: a factory console answers 404, so a factory screen can never
show a stock photo where its camera should be. Fixed names only, never a path from the URL.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .console_deps import DemoMode

demo_router = APIRouter(tags=["console"])
_FOLDER = Path(__file__).resolve().parents[1] / "static" / "demo"
_NAMA = re.compile(r"(frame-[1-5]\.webp|frames\.json)")
# The frames never change within a release; an hour keeps the 2.6 s feed swap off the network.
_CACHE = "max-age=3600"


@demo_router.get("/demo/{nama}")
def demo_frame(nama: str, demo_mode: DemoMode) -> FileResponse:
    if not demo_mode or not _NAMA.fullmatch(nama):
        raise HTTPException(status_code=404)
    return FileResponse(_FOLDER / nama, headers={"Cache-Control": _CACHE})
