"""Integrasi Last Sync: dari foto di disk line sampai baris di layar operator.

Yang dirangkai tanpa tiruan di tengahnya:

- tiga line, masing-masing dengan `BatchUploadWorker` + `UploadManifest` ASLI dan
  foto sungguhan di disk; `RuntimeState.status_unggah` dipasang seperti `main.py`;
- `/internal/status` tiap line dijawab dengan `LineStatusResponse` yang asli,
  secret dicek, dilayani transport ASGI in-process;
- `LineClient` + `LineStatusWorker` + `ConsoleService.state()` konsol yang asli;
- `MasterDataWorker` dan `CekSinkronWorker` asli di atas `ErpClient` asli, dengan
  AutoERP dijawab `httpx.MockTransport`; `R2Uploader.cek()` asli di atas klien S3
  tiruan;
- `StatusSinkron` di atas console.db sungguhan (jam sinkron selamat dari restart);
- baris yang dijawab server digambar `barisSinkron` di console.html lewat node.

Yang tiruan: `put` ke R2 dan klien S3 (jaringan), jawaban server AutoERP, dan jam.
Controller `/internal/status` yang asli menyeret torch lewat `core.dependencies`,
jadi app line di sini memanggil `unggah_dari_state` yang sama dengan controller;
controller-nya sendiri dibuktikan di tests/e2e/test_internal_status_alarm.py.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from botocore.exceptions import ClientError
from fastapi import FastAPI, Header, HTTPException

from palmgrade.core.config import LineEndpoint, Settings
from palmgrade.domain.sinkron import unggah_dari_state
from palmgrade.integrations.erp.client import ErpClient
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.integrations.upload.r2_uploader import R2Uploader
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.schemas.internal_schema import LineStatusResponse
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.status_sinkron import StatusSinkron
from palmgrade.workers.batch_upload_worker import BatchUploadWorker
from palmgrade.workers.cek_sinkron_worker import CekSinkronWorker
from palmgrade.workers.line_status_worker import LineStatusWorker
from palmgrade.workers.master_data_worker import MasterDataWorker
from palmgrade.workers.runtime_state import RuntimeState

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")
SECRET = "rahasia-integrasi-sinkron"
ERP = "http://erp.local"
MESIN = {
    1: "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01",
    2: "a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02",
    3: "ad5f7bb9-c06d-4e87-8282-ce450ae331ec",
}
LINES = tuple(LineEndpoint(f"line-{n}", f"Line {n}", 8000 + n, MESIN[n]) for n in (1, 2, 3))
# 27 Sep 2026 14:00 WIB. Jam pura-pura yang sama untuk line dan konsol.
AWAL = 1_790_492_400.0


class _Jam:
    def __init__(self) -> None:
        self.now = AWAL

    def __call__(self) -> float:
        return self.now


class _R2Put:
    """`put` ke R2: satu-satunya bagian upload yang menyentuh jaringan."""

    def __init__(self) -> None:
        self.gagal = False
        self.naik: list[str] = []

    def put(self, local_path, r2_key) -> None:
        if self.gagal:
            raise ConnectionError("Could not connect to the endpoint URL")
        self.naik.append(r2_key)


class Line:
    """Satu proses line: Settings + RuntimeState + worker upload + /internal/status."""

    def __init__(self, root: Path, n: int, jam: _Jam) -> None:
        self.settings = replace(
            Settings(), repo_root=root / f"line-{n}", machine_id=MESIN[n], internal_secret=SECRET,
            r2_bucket="palmgrade", r2_public_url="https://captures.example", upload_api_url="",
            upload_disk_min_free_gb=0,
        )
        self.r2 = _R2Put()
        self.manifest = UploadManifest(db_path=self.settings.state_dir / "upload_manifest.db")
        self.worker = BatchUploadWorker(
            settings=self.settings, manifest=self.manifest, uploader=self.r2, jam=jam
        )
        self.state = RuntimeState()
        self.state.status_unggah = self.worker.status_unggah  # seperti main.py
        self.versi_lama = False
        self.app = self._buat_app()

    def _buat_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/internal/status")
        def status(x_internal_secret: str | None = Header(default=None)):
            if x_internal_secret != SECRET:
                raise HTTPException(status_code=401, detail="Invalid internal secret")
            jawab = LineStatusResponse(
                machine_id=self.settings.machine_id, truck_id=None, ffb_source=None,
                piston={}, alarms=[], unggah=unggah_dari_state(self.state),
            ).model_dump()
            if self.versi_lama:  # image sebelum Last Sync: field-nya belum ada
                jawab.pop("unggah")
            return jawab

        return app

    def foto(self, jumlah: int, tanggal: str = "2026-09-27") -> None:
        folder = self.settings.results_dir / tanggal
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(jumlah):
            ts = f"{tanggal}_1400{len(list(folder.glob('*.webp'))):02d}_000000"
            (folder / f"{ts}_auto.webp").write_bytes(b"webp")
            (folder / f"{ts}_auto_ripeness.json").write_text(json.dumps({
                "timestamp": f"{tanggal}T14:00:{i:02d}", "image_path": f"captures/results/{tanggal}/{ts}_auto.webp",
                "ripeness_status": "acc", "ripeness_confidence": 0.9, "tp_status": None, "tp_confidence": 0,
                "capture_type": "auto", "truck_id": None, "bounding_box": {}, "assignment_id": None,
            }))

    def batch(self) -> None:
        """Tick batch per jam. `next_retry_at` dinolkan: jam pura-pura tidak menggeser
        jam dinding yang dipakai manifest untuk jadwal ulang."""
        self.manifest._db.execute("UPDATE upload_items SET next_retry_at=0")
        self.worker.run_batch_once()


class _PerPort(httpx.AsyncBaseTransport):
    """Satu transport untuk tiga line: permintaan diarahkan menurut port-nya."""

    def __init__(self, lines: dict[int, Line]) -> None:
        self._lines = lines

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        line = self._lines.get(request.url.port)
        if line is None:
            raise httpx.ConnectError("connection refused")
        return await httpx.ASGITransport(app=line.app).handle_async_request(request)


class _AutoErp:
    """Server AutoERP: ping dan daftar data master, bisa dimatikan."""

    def __init__(self) -> None:
        self.mati = False
        self.dipanggil: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.mati:
            raise httpx.ConnectError("[Errno 8] nodename nor servname provided")
        self.dipanggil.append(request.url.path)
        if request.url.path == "/api/method/ping":
            return httpx.Response(200, json={"message": "pong"})
        return httpx.Response(200, json={"data": []})


class _S3:
    """Klien S3 untuk `R2Uploader.cek()`: 404 = R2 menjawab, objeknya saja belum ada."""

    def __init__(self) -> None:
        self.mati = False

    def head_object(self, **_):
        if self.mati:
            raise ConnectionError("Could not connect to the endpoint URL")
        raise ClientError({"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")


class Pabrik:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.jam = _Jam()
        self.lines = {8000 + n: Line(root, n, self.jam) for n in (1, 2, 3)}
        self.erp = _AutoErp()
        self.s3 = _S3()
        self.settings = replace(
            Settings(), repo_root=root / "konsol", factory_tz="Asia/Jakarta", erp_url=ERP,
            r2_bucket="palmgrade", console_line_host="http://line", internal_secret=SECRET,
        )
        self.store = ConsoleStore(root / "konsol" / "console.db")
        self._rakit_konsol()

    def _rakit_konsol(self) -> None:
        """Seperti console_main.py: satu StatusSinkron dibagi service dan worker."""
        self.status = StatusSinkron(self.store, erp_aktif=True, r2_aktif=True, jam=self.jam)
        klien_line = LineClient(self.settings, transport=_PerPort(self.lines))
        self.status_line = LineStatusWorker(LINES, klien_line, interval_s=0)
        self.service = ConsoleService(self.settings, self.store, klien_line, status_sinkron=self.status)
        self.service.lines = LINES
        self.service.line_status = self.status_line.snapshot
        erp = ErpClient(ERP, "k", "s", transport=httpx.MockTransport(self.erp))
        self.tarik = MasterDataWorker(self.store, erp, status=self.status)
        r2 = R2Uploader("acc", "k", "s", "palmgrade", client=self.s3)
        self.cek = CekSinkronWorker(self.status, erp=erp, r2=r2, interval_s=0)

    def restart_konsol(self) -> None:
        self._rakit_konsol()

    def putaran(self) -> dict:
        """Satu putaran latar konsol, lalu yang diterima layar dari polling state."""
        asyncio.run(self.status_line.run_once())
        asyncio.run(self.cek.run_once())
        return self.service.state()["sinkron"]


@pytest.fixture
def pabrik(tmp_path) -> Pabrik:
    return Pabrik(tmp_path)


def _layar(sinkron: dict, sekarang: float) -> dict:
    """Gambar dua baris Last Sync dengan fungsi layar yang asli."""
    def fungsi(nama: str) -> str:
        awal = HTML.index(f"function {nama}(")
        return HTML[awal : HTML.index("\n}", awal) + 2]

    skrip = (
        'const KOSONG = "-"; const lokal = () => "id-ID";\n'
        'const t = (k) => ({sinkronTerputus: "Terputus sejak {jam}", sinkronMenunggu: "{n} menunggu",'
        ' sinkronBelum: "Belum pernah", sinkronTidakDipakai: "Tidak dipakai"}[k] || k);\n'
        + "\n".join(fungsi(n) for n in ("jamSinkron", "barisSinkron", "judulSinkron"))
        + f"\nconst s = {json.dumps(sinkron)};"
        + f"\nconsole.log(JSON.stringify({{erp: barisSinkron(s.autoerp, {sekarang}),"
        + f" cloud: barisSinkron(s.cloud, {sekarang}), judul: judulSinkron(s.cloud, {sekarang})}}));"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30,
                           env={"TZ": "Asia/Jakarta", "PATH": ""})
    assert hasil.returncode == 0, hasil.stderr[-800:]
    return json.loads(hasil.stdout)


def test_foto_naik_dan_data_master_tertarik_menggeser_kedua_jam(pabrik):
    for line in pabrik.lines.values():
        line.foto(2)
        line.batch()
    asyncio.run(pabrik.tarik.run_once())

    sinkron = pabrik.putaran()

    assert (sinkron["autoerp"]["keadaan"], sinkron["autoerp"]["terakhir"]) == ("tersambung", AWAL)
    cloud = sinkron["cloud"]
    assert (cloud["keadaan"], cloud["terakhir"], cloud["antre"]) == ("tersambung", AWAL, 0)
    assert [(p["line_code"], p["terbaca"], p["terakhir"]) for p in cloud["per_line"]] == [
        ("line-1", True, AWAL), ("line-2", True, AWAL), ("line-3", True, AWAL)
    ]
    assert all(len(line.r2.naik) == 2 for line in pabrik.lines.values())
    assert "/api/method/ping" in pabrik.erp.dipanggil


def test_ping_menjaga_status_tapi_tidak_menggeser_jam_sinkron(pabrik):
    """Cek tiap menit menjawab "hidup SEKARANG", bukan "data terakhir masuk"."""
    asyncio.run(pabrik.tarik.run_once())
    pabrik.jam.now += 1_800

    sinkron = pabrik.putaran()

    assert (sinkron["autoerp"]["keadaan"], sinkron["autoerp"]["terakhir"]) == ("tersambung", AWAL)


def test_satu_line_gagal_upload_membuat_cloud_photo_merah_dengan_sejak_dan_antrean(pabrik):
    satu, dua = pabrik.lines[8001], pabrik.lines[8002]
    satu.foto(1)
    satu.batch()
    dua.foto(3)
    dua.r2.gagal = True
    pabrik.jam.now += 3_600
    dua.batch()
    pabrik.jam.now += 3_600
    dua.batch()                               # masih gagal: "sejak" tidak bergeser

    cloud = pabrik.putaran()["cloud"]

    assert (cloud["keadaan"], cloud["sejak"], cloud["antre"]) == ("terputus", AWAL + 3_600, 3)
    assert cloud["terakhir"] == AWAL          # jam foto terakhir yang benar-benar naik
    per_line = {p["line_code"]: p for p in cloud["per_line"]}
    assert (per_line["line-2"]["sejak"], per_line["line-2"]["antre"]) == (AWAL + 3_600, 3)


def test_line_mati_atau_versi_lama_tidak_membuat_cloud_photo_merah(pabrik):
    """Kartu line sendiri sudah menulis OFFLINE; baris ini bicara soal cloud."""
    pabrik.lines[8001].foto(1)
    pabrik.lines[8001].batch()
    del pabrik.lines[8002]                    # line-2 mati: koneksi ditolak
    pabrik.lines[8003].versi_lama = True      # line-3 belum kenal field `unggah`

    cloud = pabrik.putaran()["cloud"]

    assert cloud["keadaan"] == "tersambung"
    assert [(p["line_code"], p["terbaca"]) for p in cloud["per_line"]] == [
        ("line-1", True), ("line-2", False), ("line-3", False)
    ]


def test_secret_salah_berarti_line_tidak_terbaca_bukan_cloud_putus(pabrik):
    pabrik.settings = replace(pabrik.settings, internal_secret="salah")
    pabrik.restart_konsol()

    cloud = pabrik.putaran()["cloud"]

    assert all(not p["terbaca"] for p in cloud["per_line"])
    assert cloud["keadaan"] == "tersambung"   # cek R2 dari konsol sendiri berhasil


def test_autoerp_dan_r2_mati_lalu_pulih(pabrik):
    asyncio.run(pabrik.tarik.run_once())
    pabrik.erp.mati = pabrik.s3.mati = True
    pabrik.jam.now += 120

    putus = pabrik.putaran()
    asyncio.run(pabrik.tarik.run_once())      # tarikan 5 menit gagal juga

    pabrik.erp.mati = pabrik.s3.mati = False
    pabrik.jam.now += 600
    pulih = pabrik.putaran()

    assert (putus["autoerp"]["keadaan"], putus["autoerp"]["sejak"]) == ("terputus", AWAL + 120)
    assert (putus["cloud"]["keadaan"], putus["cloud"]["sejak"]) == ("terputus", AWAL + 120)
    assert (pulih["autoerp"]["keadaan"], pulih["autoerp"]["sejak"]) == ("tersambung", None)
    assert (pulih["cloud"]["keadaan"], pulih["cloud"]["sejak"]) == ("tersambung", None)
    assert pulih["autoerp"]["terakhir"] == AWAL   # ping bukan data: jamnya tetap


def test_jam_sinkron_selamat_dari_restart_konsol(pabrik):
    asyncio.run(pabrik.tarik.run_once())
    pabrik.jam.now += 86_400

    pabrik.restart_konsol()
    baru_nyala = pabrik.service.state()["sinkron"]["autoerp"]

    assert (baru_nyala["keadaan"], baru_nyala["terakhir"]) == ("memeriksa", AWAL)


@pytest.mark.skipif(NODE is None, reason="node tidak ada")
def test_yang_dijawab_server_tergambar_di_layar(pabrik):
    satu, dua = pabrik.lines[8001], pabrik.lines[8002]
    satu.foto(1)
    satu.batch()                              # 14:00 WIB
    asyncio.run(pabrik.tarik.run_once())
    dua.foto(4)
    dua.r2.gagal = True
    pabrik.jam.now += 2_400                   # 14:40 WIB
    dua.batch()
    pabrik.jam.now += 600

    layar = _layar(pabrik.putaran(), pabrik.jam.now)

    assert layar["erp"] == {"kelas": "tersambung", "jam": "14.00", "ket": ""}
    assert layar["cloud"] == {"kelas": "terputus", "jam": "14.00", "ket": "Terputus sejak 14.40 · 4 menunggu"}
    judul = layar["judul"].split("\n")
    assert "line-1: 14.00" in judul
    assert "line-2: Terputus sejak 14.40 · 4 menunggu" in judul
    assert "line-3: Belum pernah" in judul
