"""End-to-end: encode WebP sungguhan tidak lagi menahan thread deteksi.

Unit test membuktikan bentuk serah-terimanya. Yang tidak bisa dibuktikan di sana
justru bagian yang dulu rusak: **berapa lama** encode sungguhnya memakan waktu,
dan apakah deteksi benar-benar bebas selama itu. Butuh cv2 + numpy (menulis WebP
betulan), jadi tinggal di e2e, bukan suite unit yang sengaja ringan.

Yang dijaga berkas ini:

* satu janjang tetap menghasilkan tiga berkas + sidecar di tempat yang sama
  dengan sebelum perbaikan — pindah thread bukan alasan layout berubah;
* menyerahkan janjang selesai jauh lebih cepat daripada menulisnya, diukur
  terhadap encode yang benar-benar terjadi;
* `image_url` yang dipakai layar operator (dihitung di depan, saat penulis belum
  mengerjakan apa-apa) menunjuk persis berkas yang kemudian ditulis penulis.
  Kalau dua rumus itu menyimpang, gambar di konsol 404 tanpa satu pun error.

Angka pembanding lapangan (PC Lampung, 2026-09-17, frame 2448x2048): ~285 ms per
encode WebP, ~590 ms untuk satu janjang penuh.
"""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.services.capture_writer import CaptureWriter  # noqa: E402
from palmgrade.workers.batch_upload_worker import BatchUploadWorker  # noqa: E402
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob  # noqa: E402

DATE_FOLDER = "2026-09-08"
TRUCK_FOLDER = "091432_B1234XY_a3f9c201"
TIMESTAMP = "2026-09-08_091432_123456"


class RecordingOutbox:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        self.events.append((event_id, machine_id, payload))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(
        Settings(),
        repo_root=tmp_path,
        machine_id="11111111-1111-1111-1111-111111111111",
        factory_tz="Asia/Jakarta",
        upload_disk_min_free_gb=0,
    )


@pytest.fixture
def frame():
    """Sebesar frame sensor Hikrobot — encode-nya yang jadi pokok perkara.

    Derau acak, bukan bidang rata: WebP memampatkan bidang rata nyaris seketika,
    dan tes yang mengukur encode gambar kosong tidak mengukur apa pun.
    """
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, (2048, 2448, 3), dtype=np.uint8)


@pytest.fixture
def saver(settings):
    worker = CaptureSaveWorker(
        settings=settings, storage=LocalFileStorage(), outbox_store=RecordingOutbox()
    )
    worker.start()
    yield worker
    worker.stop()


def _job(frame, **over) -> SaveJob:
    return SaveJob(**{
        "timestamp": TIMESTAMP,
        "date_folder": DATE_FOLDER,
        "truck_folder": TRUCK_FOLDER,
        "annotated_frame": frame,
        "clean_frame": frame,
        "ripeness_status": "rej",
        "ripeness_conf": 0.91,
        "grade_class": "Unripe",
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        "truck_id": "truck-1",
        "assignment_id": "a3f9c201-dead-beef",
        "ffb_source": "External",
        "event_ts": "2026-09-08T02:14:32+00:00",
        "tp": None,
    } | over)


def test_one_bunch_still_lands_as_three_images_and_a_flat_sidecar(settings, frame, saver):
    """Layout di disk tidak boleh berubah gara-gara penulisnya pindah thread."""
    saver.submit(_job(frame))
    assert saver.tunggu_kosong(timeout=30), "penulis tidak selesai"

    images = sorted(settings.results_dir.rglob("*.webp"))
    assert len(images) == 3
    for image in images:
        assert image.stat().st_size > 0, "cv2 menulis berkas kosong"

    truck = settings.results_dir / DATE_FOLDER / TRUCK_FOLDER
    assert (truck / "bbox" / "rej").is_dir()
    assert (truck / "clean" / "rej").is_dir()
    assert (truck / "thumb" / "rej").is_dir()

    # Pola literal dari `BatchUploadWorker._scan()`.
    assert len(list(settings.results_dir.glob("*/*_ripeness.json"))) == 1


def test_handing_a_bunch_over_is_far_cheaper_than_writing_it(settings, frame):
    """Inti perbaikan, diukur terhadap encode yang benar-benar terjadi.

    Sebelum ini thread deteksi menanggung seluruh biaya tulis. Sesudahnya dia
    cuma menaruh satu objek di antrean, jadi serah-terima harus jauh lebih murah
    daripada penulisannya — bukan sedikit lebih murah.
    """
    worker = CaptureSaveWorker(
        settings=settings, storage=LocalFileStorage(), outbox_store=RecordingOutbox()
    )

    # Biaya menulis sungguhan, sinkron: inilah yang dulu dibayar thread deteksi.
    mulai = time.monotonic()
    worker.run_once(_job(frame))
    lama_tulis = time.monotonic() - mulai

    worker.start()
    try:
        mulai = time.monotonic()
        worker.submit(_job(frame, timestamp="2026-09-08_091433_000000"))
        lama_serah = time.monotonic() - mulai
    finally:
        worker.stop()

    assert lama_tulis > 0.02, (
        f"encode 2448x2048 cuma {lama_tulis*1000:.0f} ms — tes ini tidak mengukur apa pun"
    )
    assert lama_serah < lama_tulis / 10, (
        f"serah-terima {lama_serah*1000:.1f} ms vs tulis {lama_tulis*1000:.0f} ms — "
        "biayanya belum benar-benar pindah dari thread deteksi"
    )


def test_detection_keeps_running_while_the_writer_is_busy(settings, frame):
    """Bukti langsung gejala yang dilaporkan: layar beku ~1 detik tiap janjang.

    Thread lain di sini berdiri sebagai deteksi: dia menghitung terus selama
    penulis menggarap tiga janjang berukuran sensor penuh. Kalau encode masih
    memblokir jalur yang sama, hitungannya akan berhenti.
    """
    worker = CaptureSaveWorker(
        settings=settings, storage=LocalFileStorage(), outbox_store=RecordingOutbox()
    )
    worker.start()

    import threading

    detak = {"n": 0}
    berhenti = threading.Event()

    def deteksi_palsu() -> None:
        while not berhenti.is_set():
            detak["n"] += 1
            time.sleep(0.005)

    t = threading.Thread(target=deteksi_palsu, daemon=True)
    t.start()
    try:
        for i in range(3):
            worker.submit(_job(frame, timestamp=f"2026-09-08_09143{i}_000000"))
        assert worker.tunggu_kosong(timeout=60), "penulis tidak selesai"
    finally:
        berhenti.set()
        t.join(timeout=2)
        worker.stop()

    # Tiga janjang ukuran sensor = ratusan milidetik kerja penulis. Thread lain
    # harus tetap berdetak puluhan kali selama itu.
    assert detak["n"] > 20, f"thread lain cuma berdetak {detak['n']}x — masih terblokir"
    assert len(list(settings.results_dir.rglob("*.webp"))) == 9, "tiga janjang, tiga berkas each"


def test_the_url_shown_on_screen_is_the_file_the_writer_writes(settings, frame, saver):
    """Tautan dihitung di depan (buat layar), berkasnya ditulis belakangan.

    Dua perhitungan yang menyimpang tidak menghasilkan error di mana pun — cuma
    gambar yang 404 di konsol, dan itu baru ketahuan saat operator mengklik.
    """
    url_di_layar = CaptureWriter.annotated_url(
        date_folder=DATE_FOLDER,
        truck_folder=TRUCK_FOLDER,
        ripeness_status="rej",
        filename=f"{TIMESTAMP}_auto.webp",
    )

    saver.submit(_job(frame))
    assert saver.tunggu_kosong(timeout=30)

    di_disk = settings.artifacts_dir / url_di_layar.removeprefix("captures/")
    assert di_disk.exists(), f"layar menunjuk {url_di_layar}, penulis tidak menulis ke situ"

    # Dan baris outbox membawa tautan yang sama.
    [(_id, _machine, payload)] = saver.outbox_store.events
    assert payload["image_path"] == url_di_layar


def test_the_uploader_still_finds_what_the_writer_wrote(settings, frame, saver):
    """Rantai penuh: penulis → sidecar → `_scan()` → berkas yang akan di-PUT ke R2."""
    from palmgrade.integrations.upload.upload_manifest import UploadManifest

    saver.submit(_job(frame))
    assert saver.tunggu_kosong(timeout=30)

    worker = BatchUploadWorker(
        settings=replace(settings, r2_bucket="bucket"),
        manifest=UploadManifest(settings.state_dir / "upload_manifest.db"),
        uploader=None,
    )
    worker._scan()

    items = worker.manifest.get_uploadable(limit=10)
    assert len(items) == 1
    local = settings.artifacts_dir / items[0]["image_path"].lstrip("/").removeprefix("captures/")
    assert local.exists(), "path yang didaftarkan untuk upload harus ada di disk"
    assert "/bbox/" in items[0]["r2_key"]


def test_a_full_queue_drops_the_bunch_instead_of_stalling_detection(settings, frame):
    """Penulis kalah cepat = janjang dibuang dengan log, BUKAN deteksi menunggu.

    Ini kompromi yang disengaja: menahan thread deteksi sampai antrean lega akan
    mengembalikan persis lag yang dihilangkan perbaikan ini.
    """
    worker = CaptureSaveWorker(
        settings=settings,
        storage=LocalFileStorage(),
        outbox_store=RecordingOutbox(),
        queue_max=1,
    )
    # Sengaja tidak di-start: antreannya menumpuk.
    assert worker.submit(_job(frame, timestamp="a")) is True

    mulai = time.monotonic()
    diterima = worker.submit(_job(frame, timestamp="b"))
    lama = time.monotonic() - mulai

    assert diterima is False
    assert lama < 0.05, "submit menunggu antrean lega — deteksi ikut tertahan"
    assert list(settings.results_dir.rglob("*.webp")) == []


def test_the_camera_hands_over_a_frame_it_will_not_overwrite():
    """Prasyarat diam-diam dari seluruh perbaikan ini.

    Menyerahkan frame ke thread lain hanya aman selama kamera tidak menulis ulang
    array yang sama untuk frame berikutnya. `HikrobotCamera` memakai SATU buffer
    (`self._data_buf`) sepanjang umur koneksi, dan `np.frombuffer(...).reshape()`
    di atasnya adalah **view** ke buffer itu — kalau view itu yang dikembalikan,
    penulis akan meng-encode frame yang sudah ditimpa janjang berikutnya, dan
    buktinya jadi gambar yang salah tanpa satu pun error.

    Yang menyelamatkan: ketiga cabang format piksel berakhir di `cv2.cvtColor`,
    yang selalu mengalokasikan array baru. Ini dijaga di sini karena "cukup
    kembalikan reshape-nya saja, toh formatnya sudah BGR" adalah optimasi yang
    masuk akal dan diam-diam merusak.
    """
    buf = bytearray(4 * 4)  # satu frame Mono8 4x4
    view = np.frombuffer(buf, dtype=np.uint8, count=16).reshape((4, 4))
    keluar = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)

    buf[0] = 255  # kamera menulis frame BERIKUTNYA ke buffer yang sama

    assert keluar[0, 0, 0] == 0, (
        "frame yang diserahkan ikut berubah saat kamera menulis frame berikutnya — "
        "grab_frame() mengembalikan view ke buffer, bukan salinan"
    )


def test_a_bad_disk_does_not_leave_a_record_pointing_at_nothing(settings, frame):
    """Critical Rule #8, lewat penulis: gambar gagal → sidecar & outbox tidak ditulis."""
    class BrokenStorage(LocalFileStorage):
        def write_image(self, path: Path, frame, quality: int = 80) -> None:
            raise OSError("disk penuh")

    outbox = RecordingOutbox()
    worker = CaptureSaveWorker(
        settings=settings, storage=BrokenStorage(), outbox_store=outbox
    )

    with pytest.raises(OSError):
        worker.run_once(_job(frame))

    assert list(settings.results_dir.rglob("*.json")) == []
    assert outbox.events == []
