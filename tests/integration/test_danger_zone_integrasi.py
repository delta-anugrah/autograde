"""Integrasi Danger Zone: konsol ↔ tiga line SUNGGUHAN, berkas sungguhan.

Yang dirangkai tanpa tiruan di tengahnya:

- `BahayaService` konsol + `LineClient` asli (HTTP sungguhan lewat transport
  ASGI in-process, dengan secret yang sungguhan dicek);
- tiga app line berisi router Danger Zone yang ASLI (`routes/internal_bahaya`),
  masing-masing dengan `Settings` dan folder sendiri berbentuk PC pabrik;
- `hapus_kalau_diminta` yang ASLI sebagai "boot berikutnya".

Yang tiruan cuma `/health` dan `/health/detail` line (aslinya menarik torch),
dan "restart" (proses sungguhan keluar lewat `os._exit`; di sini line ditandai
mati lalu boot-nya dijalankan tangan).
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Response

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.bahaya import MODE_SEMUA, MODE_TRANSAKSI
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineClient, LinePlcTolak
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.routes.internal_bahaya import buat_router
from palmgrade.services.bahaya_service import BahayaDitolak, BahayaService
from palmgrade.services.hapus_data_line import PENANDA, hapus_kalau_diminta
from palmgrade.workers.runtime_state import RuntimeState

SECRET = "rahasia-integrasi"
MESIN = {
    1: "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01",
    2: "a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02",
    3: "ad5f7bb9-c06d-4e87-8282-ce450ae331ec",
}
LINES = tuple(LineEndpoint(f"line-{n}", f"Line {n}", 8000 + n, MESIN[n]) for n in (1, 2, 3))


class Line:
    """Satu proses line: Settings + RuntimeState + app dengan router asli."""

    def __init__(self, root: Path, n: int) -> None:
        self.settings = replace(
            Settings(), repo_root=root / f"line-{n}", machine_id=MESIN[n], internal_secret=SECRET
        )
        self.state = RuntimeState()
        self.mati = False
        self.keluar_diminta: list[float] = []
        # Yang dilaporkan /health/detail — biasanya sama dengan state, kecuali
        # test ingin meniru truk yang dipasang SESUDAH konsol memeriksa.
        self.laporan_truk: str | None = None
        self._isi()
        self.app = FastAPI()
        self.app.include_router(
            buat_router(settings=lambda: self.settings, state=lambda: self.state, keluar=self._keluar)
        )

        @self.app.get("/health")
        def health():
            return Response(status_code=503) if self.mati else {"status": "ok"}

        @self.app.get("/health/detail")
        def detail():
            if self.mati:
                return Response(status_code=503)
            return {"status": "ok", "outbox_pending": 0, "current_assignment_id": self.laporan_truk}

    def _keluar(self, jeda: float) -> None:
        self.keluar_diminta.append(jeda)
        self.mati = True  # os._exit di pabrik

    def boot(self) -> dict | None:
        """Boot berikutnya: yang dijalankan awal lifespan main.py."""
        self.mati = False
        return hapus_kalau_diminta(self.settings.artifacts_dir, self.settings.state_dir)

    def _isi(self) -> None:
        s = self.settings
        foto = s.results_dir / "2026-09-25" / "101500_B1234XY_abcd1234"
        for varian in ("bbox/Ripe", "clean/Ripe", "thumb/Ripe"):
            (foto / varian).mkdir(parents=True)
            (foto / varian / "20260925_101501_auto.webp").write_bytes(b"w" * 64)
        (s.results_dir / "2026-09-25" / "20260925_101501_ripeness.json").write_text("{}")
        (s.artifacts_dir / "outbox.db").write_bytes(b"outbox")
        (s.artifacts_dir / "license.db").write_bytes(b"lisensi")
        s.state_dir.mkdir(parents=True)
        (s.state_dir / "upload_manifest.db").write_bytes(b"manifest")

    def isi_artifacts(self) -> list[str]:
        return sorted(p.name for p in self.settings.artifacts_dir.iterdir())


class _PerPort(httpx.AsyncBaseTransport):
    """Satu transport untuk tiga line: permintaan diarahkan menurut port-nya."""

    def __init__(self, lines: dict[int, Line]) -> None:
        self._t = {port: httpx.ASGITransport(app=ln.app) for port, ln in lines.items()}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._t[request.url.port].handle_async_request(request)


@pytest.fixture
def pabrik(tmp_path, monkeypatch):
    monkeypatch.setenv("REKAMAN_DIR", str(tmp_path / "videos"))
    lines = {8000 + n: Line(tmp_path, n) for n in (1, 2, 3)}
    klien = LineClient(
        Settings(console_line_host="http://line", internal_secret=SECRET),
        transport=_PerPort(lines),
    )
    store = ConsoleStore(tmp_path / "console" / "console.db")
    with store._lock, store._db:
        store._db.execute(
            "INSERT INTO inspections (event_id, machine_id, line_code, work_date, timestamp, "
            "ripeness_status, capture_type, received_at) VALUES ('e1', 'm', 'line-1', "
            "'2026-09-25', '2026-09-25T01:00:00Z', 'ACC', 'auto', 1.0)"
        )
        store._db.execute("INSERT INTO trucks (id, plate_number) VALUES ('t1', 'B1234XY')")
    store.set_state("setelan_grading", '{"conf_threshold": 0.6}')
    store.upsert_operator_manual(
        {"email": "ani@pks.id", "full_name": "Ani", "password_hash": hash_password("sandi-ani-1")}
    )
    bahaya = BahayaService(
        store,
        LogStore(tmp_path / "console" / "log.db"),
        klien,
        LINES,
        ErpOutboxStore(tmp_path / "console" / "erp_outbox.db"),
        None,
        erp_aktif=True,
        hash_bawaan=hash_password("sandi-bawaan-1"),
        hash_support=hash_password("sandi-bawaan-1"),
        tunggu_mati_s=2.0,
        jeda_cek_s=0.0,
    )
    return bahaya, store, lines


def _hitung(store: ConsoleStore, tabel: str) -> int:
    with store._lock:
        return store._db.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]


def test_hapus_transaksi_dari_konsol_sampai_boot_tiap_line(pabrik):
    bahaya, store, lines = pabrik

    hasil = asyncio.run(
        bahaya.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="support@pks.id")
    )

    assert [r["ok"] for r in hasil["lines"]] == [True, True, True]
    for line in lines.values():
        # Perintah sampai lewat HTTP dengan secret yang benar: penanda ada,
        # line diminta keluar, dan konsol MENUNGGU line mati sebelum lanjut.
        assert (line.settings.artifacts_dir / PENANDA).exists()
        assert line.keluar_diminta == [1.0]
    assert _hitung(store, "inspections") == 0
    assert _hitung(store, "trucks") == 1
    assert store.get_state("setelan_grading") == '{"conf_threshold": 0.6}'

    for line in lines.values():
        boot = line.boot()
        assert boot["diminta_oleh"] == "support@pks.id"
        assert boot["gagal"] == 0
        assert line.isi_artifacts() == ["license.db"]
        assert list(line.settings.state_dir.iterdir()) == []


def test_hapus_semua_membuat_ulang_akun_bawaan(pabrik):
    bahaya, store, lines = pabrik

    asyncio.run(bahaya.hapus_data(mode=MODE_SEMUA, konfirmasi="HAPUS", oleh="s@pks.id"))

    assert _hitung(store, "trucks") == 0
    assert store.operator_by_email("ani@pks.id") is None
    assert store.operator_by_email("support@autograde.local")["role"] == "support"
    for line in lines.values():
        line.boot()
        assert line.isi_artifacts() == ["license.db"]


def test_truk_terpasang_ditolak_konsol_tidak_ada_yang_tersentuh(pabrik):
    bahaya, store, lines = pabrik
    lines[8002].laporan_truk = "assign-2"

    with pytest.raises(BahayaDitolak) as exc:
        asyncio.run(bahaya.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    assert exc.value.hambatan == [{"kode": "truk_terpasang", "line": "line-2"}]
    assert _hitung(store, "inspections") == 1
    for line in lines.values():
        assert not (line.settings.artifacts_dir / PENANDA).exists()
        assert line.keluar_diminta == []
        assert "outbox.db" in line.isi_artifacts()


def test_truk_dipasang_sesudah_konsol_memeriksa_ditolak_line_itu_sendiri(pabrik):
    """Pemeriksaan kedua di proses line: konsol melihat line-2 bebas, tapi truk
    dipasang sebelum perintahnya sampai. Line-2 menolak (409 lewat HTTP
    sungguhan) dan datanya utuh; dua line lain tetap dibersihkan."""
    bahaya, store, lines = pabrik
    lines[8002].state.current_assignment_id = "assign-telat"  # laporan_truk tetap None

    hasil = asyncio.run(bahaya.hapus_data(mode=MODE_TRANSAKSI, konfirmasi="HAPUS", oleh="s"))

    per_line = {r["line_code"]: r for r in hasil["lines"]}
    assert per_line["line-2"] == {"line_code": "line-2", "ok": False, "kode": "truk_terpasang"}
    assert not (lines[8002].settings.artifacts_dir / PENANDA).exists()
    assert lines[8002].boot() is None
    assert "outbox.db" in lines[8002].isi_artifacts()
    for port in (8001, 8003):
        lines[port].boot()
        assert lines[port].isi_artifacts() == ["license.db"]


def test_secret_salah_ditolak_line(pabrik):
    """Konsol dengan secret berbeda tidak bisa menyuruh line menghapus apa pun."""
    _bahaya, _store, lines = pabrik
    klien_salah = LineClient(
        Settings(console_line_host="http://line", internal_secret="bukan-secret-ini"),
        transport=_PerPort(lines),
    )
    with pytest.raises(LinePlcTolak) as exc:
        asyncio.run(klien_salah.hapus_data(LINES[0], mode=MODE_TRANSAKSI, diminta_oleh="x"))
    assert exc.value.status_code == 401
    assert not (lines[8001].settings.artifacts_dir / PENANDA).exists()


def test_ringkasan_membaca_line_sungguhan(pabrik):
    bahaya, _store, lines = pabrik
    videos = lines[8001].settings.videos_dir
    videos.mkdir(parents=True, exist_ok=True)
    (videos / "line-1_20260925-101500.mp4").write_bytes(b"v" * 500)
    (videos / "line-3_20260925-101500.mp4").write_bytes(b"v" * 250)
    lines[8003].mati = True

    r = asyncio.run(bahaya.ringkasan())

    assert r["aksi"]["rekaman"]["berkas"] == 1  # line-3 mati: rekamannya tak terhitung
    assert r["aksi"]["rekaman"]["bytes"] == 500
    assert r["aksi"]["transaksi"]["hambatan"] == [{"kode": "line_mati", "line": "line-3"}]


def test_hapus_rekaman_tiap_line_menghapus_miliknya_di_folder_bersama(pabrik):
    bahaya, _store, lines = pabrik
    videos = lines[8001].settings.videos_dir
    videos.mkdir(parents=True, exist_ok=True)
    for kode in ("line-1", "line-2", "line-3", "line-10"):
        (videos / f"{kode}_20260925-101500.mp4").write_bytes(b"v" * 100)

    hasil = asyncio.run(bahaya.hapus_rekaman(konfirmasi="HAPUS", oleh="s"))

    assert hasil["berkas"] == 3
    assert [p.name for p in videos.iterdir()] == ["line-10_20260925-101500.mp4"]
