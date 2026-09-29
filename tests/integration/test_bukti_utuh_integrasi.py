"""Integrasi bukti utuh (batch 2.6): penulis bukti ↔ disk ↔ batch upload ↔ manifest SQLite.

Semuanya sungguhan kecuali R2 (pencatat kunci): `CaptureSaveWorker` dengan
`LocalFileStorage` asli (WebP lewat cv2, tulisan atomik), `BatchUploadWorker`
dengan `UploadManifest` SQLite di folder sementara, dan retensinya.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.integrations.upload.upload_manifest import UploadManifest  # noqa: E402
from palmgrade.workers.batch_upload_worker import BatchUploadWorker  # noqa: E402
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob  # noqa: E402

MACHINE_ID = "11111111-1111-1111-1111-111111111111"
DAY = "2026-09-08"
TRUCK = "091432_B1234XY_a3f9c201"


class _Uploader:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def put(self, local_path, r2_key, *, content_type="image/webp") -> None:
        assert local_path.stat().st_size > 0, "berkas 0 byte sampai ke R2"
        self.keys.append(r2_key)


class _Outbox:
    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        pass


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), repo_root=tmp_path, machine_id=MACHINE_ID, factory_tz="Asia/Jakarta",
                   r2_bucket="bucket", upload_api_url="", upload_disk_min_free_gb=0,
                   upload_retention_days=0)


def _tulis_janjang_sungguhan(settings, stamp: str) -> None:
    penulis = CaptureSaveWorker(settings=settings, storage=LocalFileStorage(), outbox_store=_Outbox())
    penulis.start()
    try:
        frame = np.random.default_rng(0).integers(0, 255, (96, 128, 3), dtype=np.uint8)
        penulis.submit(SaveJob(
            timestamp=stamp, date_folder=DAY, truck_folder=TRUCK,
            annotated_frame=frame, clean_frame=frame,
            ripeness_status="acc", ripeness_conf=0.9, grade_class="Ripe",
            bounding_box={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
            truck_id="truck-1", assignment_id="a3f9c201-dead-beef", ffb_source="External",
            event_ts="2026-09-08T02:14:32+00:00",
        ))
        assert penulis.tunggu_kosong(timeout=30)
    finally:
        penulis.stop(timeout=2)


def _janjang_lama_nol_byte(settings, stamp: str):
    """Disk pabrik sebelum batch 2.6: listrik padam saat foto ditulis."""
    annotated = settings.results_dir / DAY / TRUCK / "bbox" / "Ripe" / f"{stamp}_auto.webp"
    annotated.parent.mkdir(parents=True, exist_ok=True)
    annotated.write_bytes(b"")
    sidecar = settings.results_dir / DAY / f"{stamp}_auto_ripeness.json"
    sidecar.write_text(json.dumps({
        "timestamp": "2026-09-08T02:10:00+00:00",
        "image_path": f"captures/results/{DAY}/{TRUCK}/bbox/Ripe/{stamp}_auto.webp",
        "ripeness_status": "ACC", "capture_type": "auto",
    }))
    return annotated, sidecar


def test_nol_byte_tidak_pernah_naik_dan_selamat_dari_retensi_dua_batch(settings):
    _tulis_janjang_sungguhan(settings, f"{DAY}_021432_781225")
    lama_foto, lama_sidecar = _janjang_lama_nol_byte(settings, f"{DAY}_021000_000001")
    manifest = UploadManifest(db_path=settings.state_dir / "upload_manifest.db")
    uploader = _Uploader()
    worker = BatchUploadWorker(settings=settings, manifest=manifest, uploader=uploader)

    worker.run_batch_once()
    worker.run_batch_once()  # yang diracun tidak dicoba lagi, dan tidak disapu retensi

    assert sorted(k.split("/")[-3] for k in uploader.keys) == ["bbox", "thumb"]
    assert manifest.counts()["poisoned"] == 1
    assert lama_foto.exists() and lama_sidecar.exists()
    # Janjang yang utuh naik, `done`, lalu disapu retensi 0 hari seperti biasa.
    assert manifest.counts()["done"] == 0
    assert not (settings.results_dir / DAY / f"{DAY}_021432_781225_auto_ripeness.json").exists()


def test_foto_nol_byte_yang_ditulis_ulang_utuh_naik_lalu_ikut_retensi(settings):
    """Racun karena tidak utuh bukan jalan buntu: tulisan utuh berikutnya naik seperti biasa."""
    lama_foto, lama_sidecar = _janjang_lama_nol_byte(settings, f"{DAY}_021000_000001")
    manifest = UploadManifest(db_path=settings.state_dir / "upload_manifest.db")
    uploader = _Uploader()
    worker = BatchUploadWorker(settings=settings, manifest=manifest, uploader=uploader)
    worker.run_batch_once()
    assert manifest.counts()["poisoned"] == 1 and uploader.keys == []

    frame = np.full((96, 128, 3), 90, dtype=np.uint8)
    LocalFileStorage().write_image(lama_foto, frame, quality=65)  # penulis atomik yang sama
    worker.run_batch_once()

    assert uploader.keys == [f"{MACHINE_ID}/results/{DAY}/{TRUCK}/bbox/Ripe/{DAY}_021000_000001_auto.webp"]
    assert manifest.counts()["poisoned"] == 0
    assert worker.status_unggah()["rusak"] == 0
    # Sesudah naik ia item `done` biasa: retensi 0 hari menyapunya.
    assert not lama_foto.exists() and not lama_sidecar.exists()
