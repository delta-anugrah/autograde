"""Satu rantai sungguhan: janjang lewat ingest lalu difoto lewat `/captures/line-1`,
lane konsol yang sama persis dengan yang dipasang `console_main.py`.

Membuktikan batas Task 7 lawan komponen yang benar-benar dirakit: operator yang
masuk melihat fotonya sendiri, operator yang keluar lagi ditolak, dan basis data
line tidak pernah terunduh walau sesi sedang hidup.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes import console as console_routes
from palmgrade.routes.captures import CapturesBersesi
from palmgrade.routes.console_deps import SESSION_COOKIE, get_auth_service, get_console_service
from palmgrade.routes.console_ingest import ingest_router
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

SECRET = "integrasi-secret"
EMAIL = "budi@pks.test"
SANDI = "sawit2026"


class _LineDiam:
    """Line tidak dipanggil di alur ini; ada supaya service bisa dirakit."""

    async def assign_truck(self, line, **_kw) -> None: ...

    async def manual_reject(self, line, **_kw) -> None: ...


def _rakit(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    settings = replace(
        Settings(), repo_root=tmp_path, webhook_secret=SECRET, factory_tz="Asia/Jakarta"
    )
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_manual(
        {"email": EMAIL, "full_name": "Pak Budi", "password_hash": hash_password(SANDI)}
    )
    service = ConsoleService(settings, store, _LineDiam())
    (settings.artifacts_dir / "line-1").mkdir(parents=True, exist_ok=True)

    app = FastAPI()
    app.include_router(console_routes.router)
    app.include_router(ingest_router, prefix=settings.backend_api_ver)
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.mount(
        "/captures/line-1",
        CapturesBersesi(
            directory=str(settings.artifacts_dir / "line-1"),
            sesi=lambda: AuthService(store),
            cookie=SESSION_COOKIE,
        ),
    )
    return app, service, settings


def _tulis_foto(settings, ts) -> str:
    rel = f"results/{ts:%Y-%m-%d}/x.webp"
    berkas = settings.artifacts_dir / "line-1" / rel
    berkas.parent.mkdir(parents=True, exist_ok=True)
    berkas.write_bytes(b"RIFFwebp")
    return f"captures/{rel}"


def _kirim(client, service, settings, *, image_path, ts, assignment="a-int-1"):
    body = {
        "event_id": str(uuid.uuid4()),
        "machine_id": service.lines[0].machine_id,
        "timestamp": ts.isoformat(),
        "prediction": "Acc",
        "ripeness_status": "ACC",
        "ripeness_confidence": 0.9,
        "capture_type": "auto",
        "assignment_id": assignment,
        "image_path": image_path,
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
    }
    r = client.post(
        f"{settings.backend_api_ver}/internal/vision/events",
        json=body,
        headers={"x-webhook-secret": SECRET},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["work_date"]


def test_foto_janjang_hanya_untuk_yang_masuk(tmp_path, monkeypatch):
    app, service, settings = _rakit(tmp_path, monkeypatch)
    with TestClient(app) as c:
        ts = datetime.now(UTC) - timedelta(minutes=1)
        rel = _tulis_foto(settings, ts)
        work_date = _kirim(c, service, settings, image_path=rel, ts=ts)

        assert c.post(
            "/api/console/login", json={"email": EMAIL, "sandi": SANDI}
        ).status_code == 200

        r = c.get("/api/console/history", params={"work_date": work_date})
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "janjang yang baru dikirim harus muncul di riwayat"
        image_url = items[0]["image_url"]

        foto = c.get(image_url)
        assert foto.status_code == 200
        assert foto.content == b"RIFFwebp"

        assert c.post("/api/console/logout").status_code == 200
        assert c.get(image_url).status_code == 401


def test_basis_data_line_tidak_terunduh_walau_masuk(tmp_path, monkeypatch):
    app, _service, settings = _rakit(tmp_path, monkeypatch)
    (settings.artifacts_dir / "line-1" / "outbox.db").write_bytes(b"SQLite format 3")

    with TestClient(app) as c:
        assert c.post(
            "/api/console/login", json={"email": EMAIL, "sandi": SANDI}
        ).status_code == 200
        assert c.get("/captures/line-1/outbox.db").status_code == 404
