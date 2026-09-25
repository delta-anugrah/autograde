"""Integrasi layar support: JSON server yang SUNGGUHAN → renderer layar yang SUNGGUHAN.

Unit test merender dengan data yang ditulis tangan — cocok dengan bentuk yang
dibayangkan penulis test. Yang dibuktikan di sini: bentuk yang BENAR-BENAR
dikeluarkan line (`HealthDetailSchema`, `PlcStateResponse` — schema pydantic
yang dipakai line), lewat rute konsol yang asli (`/api/console/dev/*`), dibaca
dengan benar oleh fungsi render yang ada di `console.html`. Nama field yang
diganti di satu sisi saja = test ini merah, bukan kartu kosong di pabrik.

Render dijalankan lewat node (dilewati kalau node tidak ada).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palmgrade.core.config import LineEndpoint
from palmgrade.domain.operator_auth import hash_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.console import get_auth_service, get_console_service, get_dev_service
from palmgrade.routes.console import router as console_router
from palmgrade.schemas.common_schema import HealthDetailSchema, WorkerStatus
from palmgrade.schemas.internal_schema import PlcStateResponse
from palmgrade.services.auth_service import AuthService
from palmgrade.services.dev_service import DevService

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node tidak ada")

SANDI = "sandi-integrasi-1"
LINES = (
    LineEndpoint("line-1", "Line 1", 8001, "m-1"),
    LineEndpoint("line-2", "Line 2", 8002, "m-2"),
)


def _detail(*, kamera: bool, mati: set[str]) -> dict:
    """Jawaban /health/detail persis seperti line membentuknya."""
    return HealthDetailSchema(
        status="ok",
        environment="production",
        camera_type="hikrobot",
        camera_connected=kamera,
        plc={"inputs": [False] * 12, "dropped_pulses": 0, "dropped_submissions": 0, "piston": {}},
        gpu_available=True,
        gpu_device="NVIDIA GeForce RTX 3060",
        machine_id="m",
        workers=[
            WorkerStatus(name=n, alive=n not in mati)
            for n in ("capture", "display", "processing", "capture_save", "outbox_retry", "plc")
        ],
    ).model_dump()


class _LinePalsu:
    async def health_detail(self, line: LineEndpoint) -> dict:
        if line.line_code == "line-1":
            return _detail(kamera=True, mati=set())
        return _detail(kamera=False, mati={"processing"})

    async def plc_state(self, line: LineEndpoint) -> dict:
        base = 1000 if line.line_code == "line-1" else 1003
        return PlcStateResponse(
            enabled=True, testable_coils=[base, base + 1, base + 2], coil_base=base,
            di_base=1100, device_prefix="M",
        ).model_dump()


class _Settings:
    app_version = "v9.9.9"
    machine_id = "konsol"
    environment = "production"
    lic_enabled = False  # saklar tidak sampai ke konsol...
    lic_token = "eyJ.token.terpasang"  # ...padahal tokennya sampai (Lampung 2026-09-22)


class _StubConsole:
    def __init__(self, store: ConsoleStore) -> None:
        self.store = store


@pytest.fixture
def support(tmp_path):
    store = ConsoleStore(tmp_path / "console.db")
    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_console_service] = lambda: _StubConsole(store)
    app.dependency_overrides[get_auth_service] = lambda: AuthService(store)
    app.dependency_overrides[get_dev_service] = lambda: DevService(
        LogStore(tmp_path / "log.db"), line_client=_LinePalsu(), lines=LINES, settings=_Settings()
    )
    store.upsert_operator_manual(
        {"email": "s@pks.id", "full_name": "S", "password_hash": hash_password(SANDI)}
    )
    store.set_role(store.operator_by_email("s@pks.id")["id"], "support")
    client = TestClient(app)
    assert client.post("/api/console/login", json={"email": "s@pks.id", "sandi": SANDI}).status_code == 200
    return client


def _fungsi(nama: str) -> str:
    awal = HTML.index(f"function {nama}(")
    return HTML[awal : HTML.index("\n}", awal) + 2]


def _render(fungsi: list[str], ekspresi: str):
    skrip = (
        'const esc = (s) => String(s ?? "").replace(/[&<>"\'`]/g, (c) =>'
        ' ({ "&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;","\'":"&#39;","`":"&#96;" }[c]));\n'
        'const KOSONG = "-";\n'
        'const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));\n'
        "const t = (k) => k;\n"
        + "\n".join(_fungsi(f) for f in fungsi)
        + f"\nconsole.log(JSON.stringify({ekspresi}));"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout.strip())


def test_diagnostik_dari_jawaban_line_sungguhan(support):
    lines = support.get("/api/console/dev/diagnostik").json()["lines"]
    kartu = {
        kode: _render(["tanda", "kartuDiagnostik"], f"kartuDiagnostik({json.dumps(kode)}, {json.dumps(d)})")
        for kode, d in lines.items()
    }

    # line-1 sehat: enam worker, semua centang hijau, kamera hijau.
    assert re.findall(r'<dt class="diag-worker">([^<]+)</dt>', kartu["line-1"]) == [
        "capture", "display", "processing", "capture_save", "outbox_retry", "plc",
    ]
    assert kartu["line-1"].count('class="tanda-gagal"') == 0
    assert ">6/6<" in kartu["line-1"]
    # line-2: kamera putus + worker processing mati — dua-duanya merah, judul 5/6.
    assert kartu["line-2"].count('class="tanda-gagal"') == 3  # kamera, 5/6, processing
    assert ">5/6<" in kartu["line-2"]


def test_versi_menyebut_saklar_lisensi_dari_jawaban_sungguhan(support):
    versi = support.get("/api/console/dev/versi").json()
    assert _render(["ringkasLisensi"], f"ringkasLisensi({json.dumps(versi['lisensi'])})") == (
        "lisensiSaklarMati"
    )


def test_tombol_plc_dari_jawaban_line_sungguhan(support):
    """Kelas warna diturunkan dari `coil_base` yang dikirim line — OK hijau, NG
    merah (bawaan), Error kuning — untuk base 1000 maupun 1003."""
    for kode, base in (("line-1", 1000), ("line-2", 1003)):
        data = support.get(f"/api/console/dev/plc/{kode}").json()
        html = _render(
            ["peranCoil", "alamatPlc", "kelasCoil", "isiCoilPlc"],
            f"isiCoilPlc({json.dumps(kode)}, {json.dumps(data)}, false)",
        )
        kelas = re.findall(r'class="uji-coil ([a-z]*)" data-line="[^"]+" data-coil="(\d+)"', html)
        assert kelas == [("ok", str(base)), ("", str(base + 1)), ("error", str(base + 2))], kode
