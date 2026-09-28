"""End-to-end: app konsol yang sebenarnya (`create_console_app()`), bukan app
dirakit sendiri di test. Ini yang membuktikan mount `/captures` di
`console_main.py`, bukan cuma kelas `CapturesBersesi` sendirian: regresi ke
`StaticFiles` polos akan lolos test unit/integrasi tapi kelihatan di sini.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from palmgrade import console_main
from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes.console_deps import get_auth_service, get_console_service
from palmgrade.services.auth_service import AuthService
from palmgrade.services.console_service import ConsoleService

EMAIL = "budi@pks.test"
SANDI = "sawit2026"


def _rakit(tmp_path, monkeypatch):
    settings = Settings(
        repo_root=tmp_path, console_default_hash="", console_support_hash="", erp_url="",
    )
    store = ConsoleStore(settings.console_db_path)
    store.upsert_operator_manual(
        {"email": EMAIL, "full_name": "Pak Budi", "password_hash": hash_password(SANDI)}
    )
    service = ConsoleService(settings, store, LineClient(settings))
    auth = AuthService(store)

    monkeypatch.setattr(console_main, "get_console_service", lambda: service)
    monkeypatch.setattr(console_main, "get_auth_service", lambda: auth)

    app = console_main.create_console_app()
    app.dependency_overrides[get_console_service] = lambda: service
    app.dependency_overrides[get_auth_service] = lambda: auth
    return app, settings


def test_tanpa_cookie_401(tmp_path, monkeypatch):
    app, settings = _rakit(tmp_path, monkeypatch)
    (settings.artifacts_dir / "line-1" / "results" / "2026-09-28").mkdir(parents=True, exist_ok=True)
    (settings.artifacts_dir / "line-1" / "results" / "2026-09-28" / "x.webp").write_bytes(b"RIFFwebp")

    c = TestClient(app)
    assert c.get("/captures/line-1/results/2026-09-28/x.webp").status_code == 401


def test_login_lalu_foto_200(tmp_path, monkeypatch):
    app, settings = _rakit(tmp_path, monkeypatch)
    (settings.artifacts_dir / "line-1" / "results" / "2026-09-28").mkdir(parents=True, exist_ok=True)
    (settings.artifacts_dir / "line-1" / "results" / "2026-09-28" / "x.webp").write_bytes(b"RIFFwebp")

    c = TestClient(app)
    r = c.post("/api/console/login", json={"email": EMAIL, "sandi": SANDI})
    assert r.status_code == 200

    foto = c.get("/captures/line-1/results/2026-09-28/x.webp")
    assert foto.status_code == 200
    assert foto.content == b"RIFFwebp"


def test_license_db_404(tmp_path, monkeypatch):
    app, settings = _rakit(tmp_path, monkeypatch)
    (settings.artifacts_dir / "line-1").mkdir(parents=True, exist_ok=True)
    (settings.artifacts_dir / "line-1" / "license.db").write_bytes(b"SQLite format 3")

    c = TestClient(app)
    c.post("/api/console/login", json={"email": EMAIL, "sandi": SANDI})
    assert c.get("/captures/line-1/license.db").status_code == 404


def test_license_db_huruf_besar_404(tmp_path, monkeypatch):
    app, settings = _rakit(tmp_path, monkeypatch)
    (settings.artifacts_dir / "line-1").mkdir(parents=True, exist_ok=True)
    (settings.artifacts_dir / "line-1" / "LICENSE.DB").write_bytes(b"SQLite format 3")

    c = TestClient(app)
    c.post("/api/console/login", json={"email": EMAIL, "sandi": SANDI})
    assert c.get("/captures/line-1/LICENSE.DB").status_code == 404
