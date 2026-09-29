"""Batch upload menolak bukti yang tidak utuh, tanpa menghapusnya (batch 2.6).

Sebelum penulis atomik, listrik padam di tengah tulisan meninggalkan foto atau
sidecar 0 byte bernama sah. Foto 0 byte diunggah ke R2 dan ditandai `done`;
sidecar 0 byte membuat item tanpa gambar yang juga langsung `done`. Dua-duanya
lalu disapu retensi. Berkas lama itu masih ada di disk pabrik.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from unittest.mock import Mock

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.berkas_utuh import nama_sementara
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.workers.batch_upload_worker import BatchUploadWorker

MACHINE_ID = "11111111-1111-1111-1111-111111111111"
DAY = "2026-09-08"
TRUCK = "091432_B1234XY_a3f9c201"
STAMP = f"{DAY}_021432_781225"
LOGGER = "palmgrade.workers.batch_upload_worker"


class FakeUploader:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def put(self, local_path, r2_key, *, content_type="image/webp") -> None:
        self.keys.append(r2_key)


@pytest.fixture
def settings(tmp_path) -> Settings:
    # Tanpa penerima teks (keadaan pabrik), penjaga disk mati (runner CI < 20 GB),
    # retensi 0 hari: kalau yang ditolak sempat `done`, retensi langsung menghapusnya.
    return replace(Settings(), repo_root=tmp_path, machine_id=MACHINE_ID,
                   r2_bucket="bucket", upload_api_url="", upload_disk_min_free_gb=0,
                   upload_retention_days=0)


def _janjang(settings, *, bbox: bytes = b"bbox", thumb: bytes | None = b"thumb", sidecar: str | None = None):
    day = settings.results_dir / DAY
    annotated = day / TRUCK / "bbox" / "Ripe" / f"{STAMP}_auto.webp"
    annotated.parent.mkdir(parents=True)
    annotated.write_bytes(bbox)
    if thumb is not None:
        t = day / TRUCK / "thumb" / "Ripe" / f"{STAMP}_auto.webp"
        t.parent.mkdir(parents=True)
        t.write_bytes(thumb)
    json_path = day / f"{STAMP}_auto_ripeness.json"
    json_path.write_text(sidecar if sidecar is not None else json.dumps({
        "timestamp": "2026-09-08T02:14:32.781225",
        "image_path": f"captures/results/{DAY}/{TRUCK}/bbox/Ripe/{STAMP}_auto.webp",
        "ripeness_status": "ACC", "capture_type": "auto", "assignment_id": "a-1",
    }))
    return annotated, json_path


def _run(settings):
    manifest = UploadManifest(db_path=settings.state_dir / "m.db")
    uploader = FakeUploader()
    worker = BatchUploadWorker(settings=settings, manifest=manifest, uploader=uploader)
    worker.run_batch_once()
    return manifest, uploader, worker


def test_foto_nol_byte_tidak_diunggah_dan_tidak_dihapus(settings, caplog):
    """Review Focus 5."""
    annotated, json_path = _janjang(settings, bbox=b"")
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        manifest, uploader, worker = _run(settings)

    assert uploader.keys == []
    assert manifest.counts().get("poisoned") == 1
    assert annotated.exists() and json_path.exists()
    assert any("0 byte" in r.getMessage() for r in caplog.records)
    # Last Sync: bukan "menunggu" yang tidak pernah habis, tapi terhitung rusak.
    assert worker.status_unggah()["antre"] == 0
    assert worker.status_unggah()["rusak"] == 1


def test_thumbnail_nol_byte_dilewati_foto_bukti_tetap_naik(settings, caplog):
    _janjang(settings, thumb=b"")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        # Retensi 7 hari: item `done` hari ini tidak ikut disapu sebelum diperiksa.
        manifest, uploader, _worker = _run(replace(settings, upload_retention_days=7))

    assert len(uploader.keys) == 1 and "/bbox/" in uploader.keys[0]
    assert manifest.counts().get("done") == 1
    assert any("Thumbnail" in r.getMessage() for r in caplog.records)


def test_sidecar_nol_byte_tidak_jadi_done_dan_fotonya_tidak_dihapus(settings):
    """Dulu: item tanpa gambar → `done` → retensi menghapus sidecar, fotonya yatim."""
    annotated, json_path = _janjang(settings, sidecar="")
    manifest, uploader, _worker = _run(settings)

    assert uploader.keys == []
    assert manifest.counts().get("poisoned") == 1
    assert manifest.counts().get("done", 0) == 0
    assert annotated.exists() and json_path.exists()


def test_sidecar_tanpa_image_path_diracun(settings):
    _janjang(settings, sidecar=json.dumps({"ripeness_status": "ACC", "timestamp": "x"}))
    manifest, uploader, _worker = _run(settings)
    assert uploader.keys == []
    assert manifest.counts().get("poisoned") == 1


def test_foto_sisa_tulisan_sementara_diracun_dan_dibiarkan(settings, caplog):
    """Sidecar yang menunjuk nama sementara tidak pernah diunggah sebagai bukti."""
    day = settings.results_dir / DAY
    folder = day / TRUCK / "bbox" / "Ripe"
    folder.mkdir(parents=True)
    sementara = folder / nama_sementara(f"{STAMP}_auto.webp", "a1b2c3d4")
    sementara.write_bytes(b"separuh")
    (day / f"{STAMP}_auto_ripeness.json").write_text(json.dumps({
        "timestamp": "2026-09-08T02:14:32.781225",
        "image_path": f"captures/results/{DAY}/{TRUCK}/bbox/Ripe/{sementara.name}",
        "ripeness_status": "ACC", "capture_type": "auto",
    }))
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        manifest, uploader, _worker = _run(settings)

    assert uploader.keys == []
    assert manifest.counts().get("poisoned") == 1
    assert sementara.exists()
    assert any("sementara" in r.getMessage() for r in caplog.records)


def test_sidecar_sementara_tidak_terlihat_dan_tidak_dihapus(settings):
    day = settings.results_dir / DAY
    day.mkdir(parents=True)
    sementara = day / nama_sementara(f"{STAMP}_auto_ripeness.json", "a1b2c3d4")
    sementara.write_text('{"timestamp": "2026-09-08T02:1')
    manifest, uploader, _worker = _run(settings)

    assert uploader.keys == []
    assert sum(manifest.counts().values()) == 0
    assert sementara.exists()


# --------------------------------------------------------------- pulih
# `poisoned` bukan jalan buntu untuk bukti yang tidak utuh: kalau berkas yang
# sama kemudian ditulis utuh, batch berikutnya mengunggahnya seperti biasa.


def test_foto_yang_kemudian_ditulis_utuh_naik_di_batch_berikutnya(settings, caplog):
    settings = replace(settings, upload_retention_days=7)
    annotated, _json_path = _janjang(settings, bbox=b"")
    _run(settings)
    # Masih 0 byte: tetap diracun, tidak dicoba ulang.
    manifest, uploader, _worker = _run(settings)
    assert uploader.keys == []
    assert manifest.counts()["poisoned"] == 1

    annotated.write_bytes(b"bbox utuh")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        manifest, uploader, worker = _run(settings)

    assert sorted(k.split("/")[-3] for k in uploader.keys) == ["bbox", "thumb"]
    assert manifest.counts()["poisoned"] == 0
    assert manifest.counts()["done"] == 1
    assert worker.status_unggah()["rusak"] == 0
    assert any("kini utuh" in r.getMessage() for r in caplog.records)


def test_sidecar_yang_kemudian_ditulis_utuh_naik_di_batch_berikutnya(settings):
    settings = replace(settings, upload_retention_days=7)
    _annotated, json_path = _janjang(settings, sidecar="")
    manifest, _uploader, _worker = _run(settings)
    assert manifest.counts()["poisoned"] == 1

    json_path.write_text(json.dumps({
        "timestamp": "2026-09-08T02:14:32.781225",
        "image_path": f"captures/results/{DAY}/{TRUCK}/bbox/Ripe/{STAMP}_auto.webp",
        "ripeness_status": "ACC", "capture_type": "auto",
    }))
    manifest, uploader, _worker = _run(settings)

    assert f"{MACHINE_ID}/results/{DAY}/{TRUCK}/bbox/Ripe/{STAMP}_auto.webp" in uploader.keys
    assert manifest.counts()["poisoned"] == 0
    assert manifest.counts()["done"] == 1


def test_sidecar_utuh_tapi_fotonya_nol_byte_pulih_lewat_dua_langkah(settings):
    """Sidecar pulih dulu, lalu fotonya ditolak; foto utuh kemudian naik."""
    settings = replace(settings, upload_retention_days=7)
    annotated, json_path = _janjang(settings, bbox=b"", sidecar="")
    _run(settings)
    json_path.write_text(json.dumps({
        "timestamp": "2026-09-08T02:14:32.781225",
        "image_path": f"captures/results/{DAY}/{TRUCK}/bbox/Ripe/{STAMP}_auto.webp",
        "ripeness_status": "ACC", "capture_type": "auto",
    }))
    manifest, uploader, _worker = _run(settings)
    assert uploader.keys == []
    assert manifest.counts()["poisoned"] == 1

    annotated.write_bytes(b"bbox utuh")
    manifest, uploader, _worker = _run(settings)
    assert manifest.counts()["done"] == 1


def test_racun_lain_tidak_dicoba_ulang_tiap_jam(settings):
    """Yang dipulihkan cuma bukti yang dulu tidak utuh. Ditolak API (400) tetap racun."""
    settings = replace(settings, upload_api_url="https://api.contoh.test")
    _janjang(settings)
    http = Mock()
    http.post.return_value = Mock(status_code=400, text="bad request")
    manifest = UploadManifest(db_path=settings.state_dir / "m.db")
    uploader = FakeUploader()
    for _ in range(2):
        BatchUploadWorker(settings=settings, manifest=manifest, uploader=uploader,
                          http_client=http).run_batch_once()

    assert http.post.call_count == 1
    assert manifest.counts()["poisoned"] == 1


def test_sidecar_tp_lama_tanpa_pasangan_tetap_done(settings):
    """Regresi: sidecar TP terpisah (sebelum 2026-09-20) memang tanpa gambar."""
    day = settings.results_dir / DAY
    day.mkdir(parents=True)
    (day / f"{STAMP}_auto_tp.json").write_text(json.dumps({"tp_status": "PASS"}))
    manifest, uploader, _worker = _run(settings)
    assert uploader.keys == []
    assert manifest.counts().get("poisoned", 0) == 0
