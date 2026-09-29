"""End-to-end (batch 2.6): listrik padam saat line menulis bukti, lalu line hidup
lagi dan upload jam berikutnya jalan.

Yang dilihat support: foto di R2 (viewer backoffice) tidak pernah kosong, Cloud
Photo di Last Sync tidak "menunggu" selamanya, dan foto lama yang rusak tetap di
disk untuk diperiksa. Dirangkai dengan penulis bukti, `LocalFileStorage`,
`BatchUploadWorker`, `UploadManifest`, dan mount `/captures` line yang ASLI;
padamnya ditiru `os._exit` di subprocess. R2 diganti pencatat kunci.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.domain.berkas_utuh import berkas_sementara  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.integrations.upload.upload_manifest import UploadManifest  # noqa: E402
from palmgrade.routes.captures import StaticTanpaDb  # noqa: E402
from palmgrade.workers.batch_upload_worker import BatchUploadWorker  # noqa: E402
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
MACHINE_ID = "11111111-1111-1111-1111-111111111111"
DAY = "2026-09-08"
TRUCK = "091432_B1234XY_a3f9c201"
UTUH = f"{DAY}_021432_781225"
PADAM = f"{DAY}_021440_000002"
LAMA = f"{DAY}_021000_000001"

_PADAM_SAAT_MENULIS = """
import os, sys
from pathlib import Path
import numpy as np
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage

def padam(src, dst):
    os._exit(1)

os.replace = padam
LocalFileStorage().write_image(Path(sys.argv[1]), np.full((96, 128, 3), 90, dtype=np.uint8), quality=65)
"""


class _R2:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def put(self, local_path, r2_key, *, content_type="image/webp") -> None:
        self.keys.append(r2_key)


class _Outbox:
    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        pass


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    return replace(Settings(), repo_root=tmp_path, machine_id=MACHINE_ID, factory_tz="Asia/Jakarta",
                   r2_bucket="bucket", upload_api_url="", upload_disk_min_free_gb=0)


def _bbox(settings, stamp: str) -> Path:
    return settings.results_dir / DAY / TRUCK / "bbox" / "Ripe" / f"{stamp}_auto.webp"


def _sebelum_padam(settings) -> None:
    penulis = CaptureSaveWorker(settings=settings, storage=LocalFileStorage(), outbox_store=_Outbox())
    penulis.start()
    try:
        frame = np.random.default_rng(0).integers(0, 255, (96, 128, 3), dtype=np.uint8)
        penulis.submit(SaveJob(
            timestamp=UTUH, date_folder=DAY, truck_folder=TRUCK,
            annotated_frame=frame, clean_frame=frame,
            ripeness_status="acc", ripeness_conf=0.9, grade_class="Ripe",
            bounding_box={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            truck_id="truck-1", assignment_id="a3f9c201-dead-beef", ffb_source="External",
            event_ts="2026-09-08T02:14:32+00:00",
        ))
        assert penulis.tunggu_kosong(timeout=30)
    finally:
        penulis.stop(timeout=2)


def _padam_saat_menulis(settings) -> None:
    env = {**os.environ, "PYTHONPATH": str(_REPO / "src")}
    proc = subprocess.run(
        [sys.executable, "-c", _PADAM_SAAT_MENULIS, str(_bbox(settings, PADAM))],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stderr


def _sisa_disk_lama(settings) -> None:
    """Janjang dari sebelum batch 2.6: foto 0 byte bernama sah, sidecar utuh."""
    _bbox(settings, LAMA).write_bytes(b"")
    (settings.results_dir / DAY / f"{LAMA}_auto_ripeness.json").write_text(json.dumps({
        "timestamp": "2026-09-08T02:10:00+00:00",
        "image_path": f"captures/results/{DAY}/{TRUCK}/bbox/Ripe/{LAMA}_auto.webp",
        "ripeness_status": "ACC", "capture_type": "auto",
    }))


def test_sesudah_padam_hanya_bukti_utuh_yang_naik_dan_tidak_ada_yang_dihapus(settings):
    _sebelum_padam(settings)
    _padam_saat_menulis(settings)
    _sisa_disk_lama(settings)

    # Listrik padam tidak meninggalkan foto 0 byte bernama sah.
    assert not _bbox(settings, PADAM).exists()
    sementara = [p for p in _bbox(settings, PADAM).parent.iterdir() if berkas_sementara(p.name)]
    assert len(sementara) == 1

    # Line hidup lagi; upload jam berikutnya jalan.
    r2 = _R2()
    worker = BatchUploadWorker(
        settings=settings, manifest=UploadManifest(db_path=settings.state_dir / "m.db"), uploader=r2,
    )
    worker.run_batch_once()

    assert sorted(r2.keys) == sorted([
        f"{MACHINE_ID}/results/{DAY}/{TRUCK}/bbox/Ripe/{UTUH}_auto.webp",
        f"{MACHINE_ID}/results/{DAY}/{TRUCK}/thumb/Ripe/{UTUH}_auto.webp",
    ])
    status = worker.status_unggah()
    assert status["antre"] == 0, "Cloud Photo menunggu selamanya"
    assert status["rusak"] == 1
    # Tidak ada bukti yang dihapus: foto 0 byte lama dan sisa sementara tetap di disk.
    assert _bbox(settings, LAMA).exists()
    assert sementara[0].exists()

    # Konsol dan LAN tidak pernah disajikan sisa sementara; foto utuh tetap tersaji.
    app = FastAPI()
    app.mount("/captures", StaticTanpaDb(directory=str(settings.artifacts_dir)))
    klien = TestClient(app)
    relatif = sementara[0].relative_to(settings.artifacts_dir).as_posix()
    assert klien.get(f"/captures/{relatif}").status_code == 404
    utuh = _bbox(settings, UTUH).relative_to(settings.artifacts_dir).as_posix()
    assert klien.get(f"/captures/{utuh}").status_code == 200

    # Foto lama yang rusak dipulihkan (mis. teknisi menulisnya ulang utuh):
    # upload jam berikutnya menaikkannya dan Cloud Photo tidak lagi menghitungnya rusak.
    LocalFileStorage().write_image(_bbox(settings, LAMA), np.full((96, 128, 3), 90, dtype=np.uint8), quality=65)
    worker.run_batch_once()
    assert f"{MACHINE_ID}/results/{DAY}/{TRUCK}/bbox/Ripe/{LAMA}_auto.webp" in r2.keys
    assert worker.status_unggah()["rusak"] == 0
