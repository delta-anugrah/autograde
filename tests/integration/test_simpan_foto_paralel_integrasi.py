"""Batch 6.2 with the real parts: `CaptureSaveWorker` + `CaptureWriter` + `LocalFileStorage`
(real WebP encode through cv2, real atomic writes) on a temporary disk.

Skipped where cv2 is not installed (CI), like `test_bukti_utuh_integrasi.py`; the same rules
are covered without cv2 in `tests/unit/test_capture_writer_paralel.py`.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob  # noqa: E402

MACHINE_ID = "11111111-1111-1111-1111-111111111111"
DAY = "2026-09-08"
TRUCK = "091432_B1234XY_a3f9c201"


class _Outbox:
    def __init__(self) -> None:
        self.events: list[str] = []

    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        self.events.append(event_id)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), repo_root=tmp_path, machine_id=MACHINE_ID, factory_tz="Asia/Jakarta")


def _job(stamp: str) -> SaveJob:
    acak = np.random.default_rng(7)
    return SaveJob(
        timestamp=stamp, date_folder=DAY, truck_folder=TRUCK,
        annotated_frame=acak.integers(0, 255, (512, 640, 3), dtype=np.uint8),
        clean_frame=acak.integers(0, 255, (512, 640, 3), dtype=np.uint8),
        ripeness_status="acc", ripeness_conf=0.9, grade_class="Ripe",
        bounding_box={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        truck_id="truck-1", assignment_id="a3f9c201-dead-beef", ffb_source="External",
        event_ts="2026-09-08T02:14:32+00:00",
    )


def _berkas(settings: Settings) -> dict[str, bytes]:
    akar = settings.results_dir / DAY
    return {str(p.relative_to(akar)): p.read_bytes() for p in akar.rglob("*") if p.is_file()}


def test_satu_janjang_tiga_webp_utuh_satu_sidecar_satu_baris_outbox(settings):
    outbox = _Outbox()
    penulis = CaptureSaveWorker(settings=settings, storage=LocalFileStorage(), outbox_store=outbox)
    stamp = f"{DAY}_021432_781225"

    penulis.run_once(_job(stamp))

    berkas = _berkas(settings)
    assert set(berkas) == {
        f"{TRUCK}/bbox/Ripe/{stamp}_auto.webp",
        f"{TRUCK}/clean/Ripe/{stamp}_auto.webp",
        f"{TRUCK}/thumb/Ripe/{stamp}_auto.webp",
        f"{stamp}_auto_ripeness.json",
    }
    for nama, isi in berkas.items():
        if nama.endswith(".webp"):
            assert isi[:4] == b"RIFF" and isi[8:12] == b"WEBP", f"{nama} is not a whole WebP"
    assert berkas[f"{TRUCK}/bbox/Ripe/{stamp}_auto.webp"] != berkas[f"{TRUCK}/clean/Ripe/{stamp}_auto.webp"], (
        "the two copies came from different frames and must differ"
    )
    assert len(outbox.events) == 1


def test_foto_bukti_gagal_tidak_menyisakan_clean_sidecar_maupun_baris_outbox(settings):
    """Rule 8 on a real disk: where the `bbox` folder should be there is a file, so the
    evidence copy cannot be written while the clean copy beside it can."""
    outbox = _Outbox()
    penulis = CaptureSaveWorker(settings=settings, storage=LocalFileStorage(), outbox_store=outbox)
    folder_truk = settings.results_dir / DAY / TRUCK
    folder_truk.mkdir(parents=True)
    (folder_truk / "bbox").write_bytes(b"bukan folder")

    with pytest.raises(OSError):
        penulis.run_once(_job(f"{DAY}_021432_781225"))

    assert set(_berkas(settings)) == {f"{TRUCK}/bbox"}, "something of the failed bunch stayed on disk"
    assert outbox.events == []


def test_penulis_tetap_menyimpan_janjang_berikutnya_sesudah_satu_gagal(settings):
    outbox = _Outbox()
    penulis = CaptureSaveWorker(settings=settings, storage=LocalFileStorage(), outbox_store=outbox)
    folder_truk = settings.results_dir / DAY / TRUCK
    folder_truk.mkdir(parents=True)
    penghalang = folder_truk / "bbox"
    penghalang.write_bytes(b"bukan folder")
    penulis.start()
    try:
        penulis.submit(_job(f"{DAY}_021432_000001"))
        assert penulis.tunggu_kosong(timeout=30)
        penghalang.unlink()
        penulis.submit(_job(f"{DAY}_021433_000002"))
        assert penulis.tunggu_kosong(timeout=30)
    finally:
        penulis.stop(timeout=2)

    berkas = set(_berkas(settings))
    assert f"{DAY}_021433_000002_auto_ripeness.json" in berkas
    assert not any("021432_000001" in nama for nama in berkas)
    assert len(outbox.events) == 1
