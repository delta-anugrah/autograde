"""ASGI app konsol operator (`APP_MODE=console`, port 8000).

Modul TERPISAH dari `main.py` dengan sengaja: `main.py` menarik
`core/dependencies.py` → pipelines → ultralytics → torch, dan `core/constants.py`
→ cv2. Konsol tidak butuh satupun. Memisahkan modulnya berarti layar operator
tetap hidup — dan boot dalam hitungan detik — walau satu line kamera mati (§4).
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
from .workers.erp_push_worker import ErpPushWorker
from .workers.master_data_worker import MasterDataWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = get_console_service()  # ZoneInfo(FACTORY_TZ) divalidasi di sini
    # Dua arah yang terpisah: master data ditarik dari cloud, event didorong ke
    # ERP. Keduanya boleh mati tanpa menjatuhkan layar operator — itu inti Fase 2.
    tasks = [
        asyncio.create_task(MasterDataWorker(service.settings, service.store).run_loop()),
        asyncio.create_task(ErpPushWorker(service.settings, service.store).run_loop()),
    ]
    logger.info("Konsol siap — hari kerja %s (%s)", service.today(), service.settings.factory_tz)
    yield
    for task in tasks:
        task.cancel()


def create_console_app() -> FastAPI:
    service = get_console_service()
    settings = service.settings
    app = FastAPI(title="Palmgrade Operator Console", lifespan=lifespan)

    # Gambar tetap tinggal di disk line masing-masing, di-mount read-only ke
    # sini oleh docker-compose. Serve statis — bukan dipindai (§6.2). Bentuk
    # URL-nya mencerminkan palmgrade-api: /captures/{line_code}/results/...
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
        # Sengaja lokal, bukan routes/health.py: yang itu menarik torch.
        return {"status": "ok", "mode": "console", "version": settings.app_version}

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/console")

    return app


app = create_console_app()
