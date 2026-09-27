"""Cloud Photo di Last Sync: tiap line melaporkan hasil upload fotonya.

`BatchUploadWorker` jalan tiap jam. Sesudah tiap batch ia menyimpan ringkasan kecil
(`status_unggah`) yang dibaca `/internal/status`, yang dipanggil konsol tiap detik.
Ringkasan itu dihitung SEKALI per batch, bukan per panggilan: `/internal/status`
tidak boleh menjalankan COUNT atas tabel manifest tiap detik.

Yang dihitung "menunggu" hanya foto yang belum sampai R2 (`pending`). Foto yang
sudah di R2 tapi teksnya belum terkirim ke API lama (`image_uploaded`) sudah aman
di cloud.
"""

from __future__ import annotations

import json

import pytest

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.upload_manifest import UploadManifest
from palmgrade.workers.batch_upload_worker import BatchUploadWorker


class FakeUploader:
    def __init__(self):
        self.fail = False
        self.gagal_sesudah: int | None = None
        self.naik = 0

    def put(self, local_path, r2_key):
        if self.fail or (self.gagal_sesudah is not None and self.naik >= self.gagal_sesudah):
            raise ConnectionError("R2 unreachable")
        self.naik += 1


class _Jam:
    def __init__(self, now=1_000.0):
        self.now = now

    def __call__(self):
        return self.now


def _worker(tmp_path, monkeypatch, *, bucket="palmgrade", jam=None):
    monkeypatch.setenv("MACHINE_ID", "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01")
    monkeypatch.setenv("R2_BUCKET", bucket)
    monkeypatch.setenv("R2_PUBLIC_URL", "https://img.example")
    monkeypatch.setenv("UPLOAD_API_URL", "")
    monkeypatch.setenv("UPLOAD_DISK_MIN_FREE_GB", "0")
    settings = Settings(repo_root=tmp_path)
    manifest = UploadManifest(db_path=tmp_path / "m.db")
    uploader = FakeUploader()
    worker = BatchUploadWorker(settings=settings, manifest=manifest, uploader=uploader, jam=jam or _Jam())
    return settings, manifest, worker, uploader


def _tulis(settings, n, date="2026-09-26"):
    d = settings.results_dir / date
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        ts = f"{date}_0830{i:02d}_000000"
        (d / f"{ts}_auto.webp").write_bytes(b"w")
        (d / f"{ts}_auto_ripeness.json").write_text(json.dumps({
            "timestamp": f"{date}T08:30:{i:02d}", "image_path": f"captures/results/{date}/{ts}_auto.webp",
            "ripeness_status": "acc", "ripeness_confidence": 0.9, "tp_status": None,
            "tp_confidence": 0, "capture_type": "auto", "truck_id": None,
            "bounding_box": {}, "assignment_id": None,
        }))


def test_tanpa_r2_status_tidak_dipakai(tmp_path, monkeypatch):
    _, _, worker, _ = _worker(tmp_path, monkeypatch, bucket="")
    worker.run_batch_once()

    assert worker.status_unggah()["aktif"] is False


def test_batch_berhasil_mencatat_jam_dan_antrean(tmp_path, monkeypatch):
    settings, _, worker, _ = _worker(tmp_path, monkeypatch, jam=_Jam(1_500.0))
    _tulis(settings, 2)

    worker.run_batch_once()

    s = worker.status_unggah()
    assert (s["aktif"], s["terakhir"], s["gagal_sejak"], s["antre"], s["rusak"]) == (True, 1_500.0, None, 0, 0)


def test_r2_putus_mencatat_sejak_dan_foto_yang_menunggu(tmp_path, monkeypatch):
    jam = _Jam(1_000.0)
    settings, manifest, worker, uploader = _worker(tmp_path, monkeypatch, jam=jam)
    _tulis(settings, 3)
    uploader.fail = True

    worker.run_batch_once()
    jam.now = 4_600.0
    manifest._db.execute("UPDATE upload_items SET next_retry_at=0")
    worker.run_batch_once()

    s = worker.status_unggah()
    assert (s["terakhir"], s["gagal_sejak"], s["antre"]) == (None, 1_000.0, 3)
    assert "R2 unreachable" in s["pesan"]


def test_pulih_menghapus_status_gagal(tmp_path, monkeypatch):
    jam = _Jam(1_000.0)
    settings, manifest, worker, uploader = _worker(tmp_path, monkeypatch, jam=jam)
    _tulis(settings, 1)
    uploader.fail = True
    worker.run_batch_once()

    uploader.fail = False
    jam.now = 4_600.0
    manifest._db.execute("UPDATE upload_items SET next_retry_at=0")
    worker.run_batch_once()

    s = worker.status_unggah()
    assert (s["terakhir"], s["gagal_sejak"], s["pesan"], s["antre"]) == (4_600.0, None, None, 0)


def test_status_tidak_menghitung_ulang_saat_dibaca(tmp_path, monkeypatch):
    """Dibaca tiap detik oleh konsol: tidak boleh ada query ke manifest di sini."""
    settings, manifest, worker, _ = _worker(tmp_path, monkeypatch)
    worker.run_batch_once()

    def meledak(*a, **k):
        raise AssertionError("status_unggah menanyai manifest")

    manifest.counts = meledak
    worker.status_unggah()


def test_sesudah_restart_jam_terakhir_dibaca_dari_manifest(tmp_path, monkeypatch):
    jam = _Jam(1_500.0)
    settings, manifest, worker, _ = _worker(tmp_path, monkeypatch, jam=jam)
    _tulis(settings, 1)
    worker.run_batch_once()
    uploaded_at = manifest._db.execute("SELECT MAX(uploaded_at) FROM upload_items").fetchone()[0]

    baru = BatchUploadWorker(settings=settings, manifest=manifest, uploader=FakeUploader(), jam=_Jam(9_000.0))

    assert baru.status_unggah()["terakhir"] == pytest.approx(uploaded_at)


def test_batch_tanpa_foto_tidak_menggeser_jam(tmp_path, monkeypatch):
    """Jam Cloud Photo = foto terakhir yang benar-benar naik. Batch malam tanpa foto
    tidak boleh mengaku "sinkron 02.05", lalu kembali ke jam lama sesudah line restart."""
    _, _, worker, _ = _worker(tmp_path, monkeypatch, jam=_Jam(1_500.0))

    worker.run_batch_once()

    s = worker.status_unggah()
    assert (s["terakhir"], s["gagal_sejak"]) == (None, None)


def test_putus_di_tengah_batch_tetap_menggeser_jam_foto_yang_sudah_naik(tmp_path, monkeypatch):
    settings, _, worker, uploader = _worker(tmp_path, monkeypatch, jam=_Jam(1_000.0))
    _tulis(settings, 3)
    uploader.gagal_sesudah = 2

    worker.run_batch_once()

    s = worker.status_unggah()
    assert (s["terakhir"], s["gagal_sejak"], s["antre"]) == (1_000.0, 1_000.0, 1)


def test_batch_yang_meledak_sebelum_selesai_ikut_tercatat_gagal(tmp_path, monkeypatch):
    """Tanpa ini status line membeku di nilai terakhirnya, mungkin hijau, sementara
    tidak ada foto yang naik (misal disk penuh saat memindai)."""
    _, _, worker, _ = _worker(tmp_path, monkeypatch, jam=_Jam(1_000.0))

    def meledak():
        raise OSError("No space left on device")

    worker._scan = meledak
    with pytest.raises(OSError):
        worker.run_batch_once()

    s = worker.status_unggah()
    assert s["gagal_sejak"] == 1_000.0 and "No space left" in s["pesan"]
