"""End-to-end sisi LINE (batch 2.2): Danger Zone menyuruh line keluar, dan line
menutup rapi dulu.

Support menekan Hapus data (atau Restart line, yang memakai jalan keluar yang
sama) saat janjang terakhir masih di antrean simpan. Dulu line `os._exit`
sedetik kemudian: coil PLC yang sedang ON tertinggal ON, dan janjang yang sudah
dipulse hilang tanpa foto, sidecar, maupun baris di konsol.

Dirangkai lewat HTTP sungguhan ke router Danger Zone yang ASLI, dengan
`PenutupLine` + `langkah_tutup_line` yang dipakai `main.py`, penulis bukti dan
`LocalFileStorage` asli, dan `PlcWorker` asli. Tiruannya: socket PLC, kamera,
penjadwal R2, dan `os._exit` (dicatat). Tanpa torch, jadi jalan di CI.
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import palmgrade.plc as plc  # noqa: E402
from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.plc.pulse import PulseScheduler  # noqa: E402
from palmgrade.plc.worker import PlcWorker  # noqa: E402
from palmgrade.routes.internal_bahaya import buat_router  # noqa: E402
from palmgrade.services.hapus_data_line import PENANDA, hapus_kalau_diminta  # noqa: E402
from palmgrade.services.langkah_tutup_line import langkah_tutup_line  # noqa: E402
from palmgrade.services.penutup_line import PenutupLine  # noqa: E402
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob  # noqa: E402
from palmgrade.workers.runtime_state import RuntimeState  # noqa: E402

SECRET = "e2e-keluar-secret"
HEADER = {"x-internal-secret": SECRET}
COIL_OK, COIL_NG, COIL_ERROR, COIL_ALIVE = 3, 4, 5, 11


class _CfgPlc:
    plc_coil_ok = COIL_OK
    plc_coil_ng = COIL_NG
    plc_coil_error = COIL_ERROR
    plc_coil_alive = (COIL_ALIVE,)
    plc_alive_toggle_ms = 0
    plc_poll_ms = 20
    plc_di_count = 16


class _SocketPlc:
    def __init__(self, jejak: list) -> None:
        self.jejak = jejak

    def write_coil(self, address: int, value: bool) -> bool:
        self.jejak.append(("coil", address, value))
        return True

    def read_discrete_inputs(self, start: int, count: int):
        return [False] * count

    def close(self) -> None:
        pass


class _DiskLambat(LocalFileStorage):
    def write_image(self, path, frame, quality: int = 80) -> None:
        time.sleep(0.1)
        super().write_image(path, frame, quality=quality)


class _Outbox:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        self.event_ids.append(event_id)


class _Kamera:
    def disconnect(self) -> None:
        pass


class _Penjadwal:
    def stop(self, *, tunggu: bool = True) -> None:
        pass


def _job(frame, detik: int) -> SaveJob:
    return SaveJob(
        timestamp=f"2026-09-28_1015{detik:02d}_000001",
        date_folder="2026-09-28",
        truck_folder="_belum-assign",
        annotated_frame=frame,
        clean_frame=frame,
        ripeness_status="rej",
        ripeness_conf=0.8,
        grade_class="Unripe",
        bounding_box={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        truck_id=None,
        assignment_id=None,
        ffb_source=None,
        event_ts=f"2026-09-28T03:15:{detik:02d}+00:00",
    )


@pytest.fixture
def line(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    state = RuntimeState()
    jejak: list = []
    keluar = threading.Event()

    penulis = CaptureSaveWorker(settings=settings, storage=_DiskLambat(), outbox_store=_Outbox())
    t_penulis = threading.Thread(target=penulis.run_loop, daemon=True, name="capture_save")
    t_penulis.start()
    worker = PlcWorker(
        client=_SocketPlc(jejak),
        scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
        settings=_CfgPlc(),
    )
    monkeypatch.setattr(plc, "_worker", worker, raising=False)
    t_plc = threading.Thread(target=worker.run_loop, daemon=True, name="plc")
    t_plc.start()
    state.worker_threads = [("capture_save", t_penulis, penulis), ("plc", t_plc, worker)]

    def catat_keluar(kode: int) -> None:
        jejak.append(("keluar", kode))
        keluar.set()

    penutup = PenutupLine(keluar=catat_keluar)
    penutup.pasang(
        langkah_tutup_line(
            worker_threads=state.worker_threads, penulis=penulis,
            kamera=_Kamera(), penjadwal=_Penjadwal(),
        )
    )
    app = FastAPI()
    app.include_router(
        buat_router(settings=lambda: settings, state=lambda: state, keluar=penutup.keluar_nanti)
    )
    yield TestClient(app), settings, penulis, worker, jejak, keluar
    penulis.stop(timeout=1)


def test_hapus_data_menjawab_dulu_lalu_menulis_antrean_dan_mematikan_coil_sebelum_keluar(line):
    client, settings, penulis, worker, jejak, keluar = line
    frame = np.random.default_rng(0).integers(0, 255, (96, 128, 3), dtype=np.uint8)
    worker.submit("rej")
    for detik in (1, 2, 3):
        assert penulis.submit(_job(frame, detik))

    res = client.post(
        "/internal/hapus-data",
        json={"mode": "transaksi", "diminta_oleh": "support@pks.test"},
        headers=HEADER,
    )

    assert res.status_code == 200, res.text
    assert res.json() == {"status": "menghapus", "jeda_detik": 1.0}
    assert not keluar.is_set(), "line keluar sebelum jawabannya sampai ke konsol"
    assert keluar.wait(15), "line tidak pernah keluar"

    # Tiga janjang yang masih antre saat perintah datang tertulis sebelum keluar.
    assert len(list(settings.results_dir.glob("*/*_ripeness.json"))) == 3
    assert len(penulis.outbox_store.event_ids) == 3
    # Semua coil yang pernah ditulis berakhir OFF sebelum keluar.
    i_keluar = jejak.index(("keluar", 0))
    level_akhir: dict[int, bool] = {}
    for isi in jejak[:i_keluar]:
        if isi[0] == "coil":
            level_akhir[isi[1]] = isi[2]
    assert level_akhir and all(nilai is False for nilai in level_akhir.values())

    # "Boot" berikutnya: penanda masih ada, dan data line (termasuk tiga janjang
    # tadi) dihapus seperti biasa. Menguras dulu tidak mengubah hasil hapus data.
    assert (settings.artifacts_dir / PENANDA).exists()
    hapus_kalau_diminta(settings.artifacts_dir, settings.state_dir, folder_db=settings.artifacts_dir)
    assert list(settings.results_dir.glob("*/*_ripeness.json")) == []


def test_perintah_kedua_saat_menutup_tidak_menjalankan_urutan_dua_kali(line):
    client, _settings, _penulis, _worker, jejak, keluar = line

    for _ in range(2):
        res = client.post(
            "/internal/hapus-data",
            json={"mode": "transaksi", "diminta_oleh": "support@pks.test"},
            headers=HEADER,
        )
        assert res.status_code == 200
    assert keluar.wait(15)
    time.sleep(1.2)  # beri waktu thread keluar kedua

    assert jejak.count(("keluar", 0)) == 2  # dua perintah = dua os._exit; yang pertama menang
    assert sum(1 for isi in jejak if isi == ("coil", COIL_OK, False)) == 1
