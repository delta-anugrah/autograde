"""End-to-end upgrade: antrean janjang dari sebelum batch 1 sampai di layar konsol.

Line versi lama menyimpan antrean di `artifacts/outbox.db`, folder yang juga
disajikan di `/captures`. Sesudah upgrade antrean itu diserap ke `state/`, lalu
dikirim `OutboxRetryWorker` yang ASLI ke lane ingest konsol yang ASLI. Yang
dilihat operator: janjang dari sebelum upgrade muncul di hitungan hari ini, dan
berkas antreannya tidak lagi bisa diunduh dari `/captures`.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.integrations.outbox.outbox_store import OutboxStore
from palmgrade.license.local_repo import LicenseLocalRepo
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.captures import StaticTanpaDb
from palmgrade.routes.console_deps import get_console_service
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.pindah_db_line import folder_db_line, pindahkan_db_lama
from palmgrade.workers.outbox_retry_worker import OutboxRetryWorker
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "kunci-e2e-palsu"


def _event(machine_id: str) -> dict:
    ts = datetime.now(UTC) - timedelta(minutes=1)
    return {
        "event_id": str(uuid.uuid4()), "machine_id": machine_id, "timestamp": ts.isoformat(),
        "prediction": "Acc", "ripeness_status": "ACC", "ripeness_confidence": 0.9,
        "capture_type": "auto", "image_path": f"captures/results/{ts:%Y-%m-%d}/x.webp",
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
    }


def test_antrean_lama_sampai_ke_konsol_dan_tidak_terunduh(tmp_path):
    settings = replace(
        Settings(), repo_root=tmp_path, backend_url="http://testserver",
        webhook_secret=SECRET, factory_tz="Asia/Jakarta", enable_webhook=True,
    )
    konsol = ConsoleService(settings, ConsoleStore(tmp_path / "konsol.db"), line_client=None)
    mesin = konsol.lines[0].machine_id

    lama = OutboxStore(settings.artifacts_dir / "outbox.db")
    for _ in range(2):
        body = _event(mesin)
        lama.add_event(body["event_id"], mesin, body)
    lama._db.close()
    line = FastAPI()
    line.mount("/captures", StaticTanpaDb(directory=str(settings.artifacts_dir)))
    assert TestClient(line).get("/captures/outbox.db").status_code == 404

    folder = folder_db_line(settings.artifacts_dir, settings.state_dir, di_container=False)
    outbox = OutboxStore(folder / "outbox.db")
    asyncio.run(pindahkan_db_lama(
        settings.artifacts_dir, folder, outbox=outbox, lisensi=LicenseLocalRepo(folder / "license.db"),
    ))

    app = FastAPI()
    app.include_router(ingest_router, prefix=settings.backend_api_ver)
    app.dependency_overrides[get_console_service] = lambda: konsol
    worker = OutboxRetryWorker(outbox, settings, RuntimeState())
    worker._client = TestClient(app)
    worker._flush_pending()

    assert folder == settings.state_dir
    assert outbox.pending_count() == 0
    assert konsol.store.inspection_count(konsol.today()) == 2
    assert not (settings.artifacts_dir / "outbox.db").exists()
    assert TestClient(line).get("/captures/outbox.db").status_code == 404
