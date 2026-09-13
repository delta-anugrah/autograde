"""Operator console ASGI app (`APP_MODE=console`, port 8000).

Deliberately a SEPARATE module from `main.py`: that one pulls
`core/dependencies.py` -> pipelines -> ultralytics -> torch, and
`core/constants.py` -> cv2. The console needs none of it. Splitting the module
is what keeps the operator screen alive - and booting in seconds - when a
camera line is down (plan §4).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .routes.console import get_console_service, ingest_router
from .routes.console import router as console_router
from .workers.master_data_worker import MasterDataWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = get_console_service()  # ZoneInfo(FACTORY_TZ) is validated here
    # Background links to AutoERP. Any of them may die without taking the
    # operator screen down with it.
    tasks = [
        asyncio.create_task(MasterDataWorker(service.settings, service.store).run_loop()),
    ]
    logger.info("Console ready, working day %s (%s)", service.today(), service.settings.factory_tz)
    yield
    for task in tasks:
        task.cancel()


def create_console_app() -> FastAPI:
    service = get_console_service()
    settings = service.settings
    app = FastAPI(title="Palmgrade Operator Console", lifespan=lifespan)

    # Images stay on each line's own disk, mounted read-only here by
    # docker-compose. Served statically, never scanned (plan §6.2). The URL
    # shape mirrors palmgrade-api: /captures/{line_code}/results/...
    for line in service.lines:
        line_dir = settings.artifacts_dir / line.line_code
        line_dir.mkdir(parents=True, exist_ok=True)
        app.mount(
            f"/captures/{line.line_code}",
            StaticFiles(directory=str(line_dir)),
            name=f"captures-{line.line_code}",
        )

    app.include_router(console_router)
    app.include_router(ingest_router, prefix=settings.backend_api_ver)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        # Deliberately local rather than routes/health.py: that one pulls torch.
        return {"status": "ok", "mode": "console", "version": settings.app_version}

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/console")

    return app


app = create_console_app()
