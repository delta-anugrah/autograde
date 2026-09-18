"""Menyimpan satu janjang tidak boleh menghentikan deteksi janjang berikutnya.

Diukur di PC Lampung 2026-09-17, frame kamera 2448x2048: satu janjang memakan
~590 ms di jalur simpan, dan 570 ms dari itu adalah dua encode WebP. Selama itu
`FrameProcessingWorker` berhenti — bukan melambat, berhenti — karena encode
dipanggil lurus di dalam loop deteksinya. Akibatnya berlapis dan tidak satu pun
muncul sebagai error:

* `frame_queue` (maxsize 5, drop-oldest, nol log) membuang frame yang lewat
  selama itu — 5 frame di video 8 fps, ~12 di kamera pabrik 20 fps;
* ByteTrack kehilangan ~0,6 detik gerakan, jadi janjang yang sama bisa kembali
  dengan track id baru dan terhitung dua kali;
* layar operator membeku, karena `DisplayWorker` menganggap frame YOLO terakhir
  masih segar selama 500 ms lalu jatuh ke frame mentah tanpa kotak.

Berkas ini menguji `CaptureSaveWorker` — antrean + thread penulis yang memikul
encode itu — dan satu invarian yang gampang hilang saat memindahkannya: nama
file (dan `event_id` uuid5 yang diturunkan darinya) harus lahir SAAT JANJANG
TERDETEKSI, bukan saat penulis sempat mengerjakannya.

Jalan tanpa torch/cv2: storage di-stub, frame diwakili string (CLAUDE.md § Tests).
"""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from palmgrade.core.config import Settings
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")


class RecordingStorage:
    """Stands in for `LocalFileStorage` — records instead of touching the disk."""

    def __init__(self) -> None:
        self.images: dict[str, object] = {}
        self.json: dict[str, dict] = {}
        self.thumbs: dict[str, object] = {}

    def write_image(self, path: Path, frame, quality: int = 80) -> None:
        self.images[str(path)] = frame

    def write_json(self, path: Path, payload: dict) -> None:
        self.json[str(path)] = payload

    def write_thumbnail(self, path: Path, frame, *, max_width: int, quality: int) -> None:
        self.thumbs[str(path)] = (frame, max_width, quality)


class RecordingOutbox:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        self.events.append((event_id, machine_id, payload))


def _job(**over) -> SaveJob:
    """Satu pekerjaan simpan, sebagaimana `FrameProcessingWorker` menyerahkannya."""
    return SaveJob(**{
        "timestamp": "2026-09-08_091432_123456",
        "date_folder": "2026-09-08",
        "truck_folder": "091432_B1234XY_a3f9c201",
        "annotated_frame": "ANNOTATED",
        "clean_frame": "CLEAN",
        "ripeness_status": "rej",
        "ripeness_conf": 0.91,
        "grade_class": "Ripe",
        "bounding_box": {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        "truck_id": "truck-1",
        "assignment_id": "a3f9c201-dead-beef",
        "ffb_source": "External",
        "event_ts": "2026-09-08T02:14:32+00:00",
        "tp": None,
    } | over)


@pytest.fixture
def worker(settings):
    storage = RecordingStorage()
    outbox = RecordingOutbox()
    return CaptureSaveWorker(settings=settings, storage=storage, outbox_store=outbox), storage, outbox


# ------------------------------------------------------- menyerahkan ≠ menunggu


def test_submit_does_not_write_anything_by_itself(worker):
    """Inti perbaikan: thread deteksi menyerahkan lalu lanjut, tidak menunggu.

    Kalau submit ikut menulis, kita cuma memindahkan kode tanpa memindahkan
    biayanya, dan lag 0,6 detik itu kembali persis seperti semula.
    """
    w, storage, outbox = worker

    w.submit(_job())

    assert storage.images == {}, "submit menulis gambar — encode masih di thread deteksi"
    assert storage.json == {}
    assert outbox.events == []


def test_submit_returns_immediately_even_when_the_writer_is_slow(settings):
    """Penulis yang tersendat tidak boleh menahan deteksi.

    Encode di sini sengaja dibuat 200 ms; submit harus tetap balik seketika.
    """
    mulai_menulis = threading.Event()
    lanjut = threading.Event()

    class SlowStorage(RecordingStorage):
        def write_image(self, path: Path, frame, quality: int = 80) -> None:
            mulai_menulis.set()
            lanjut.wait(timeout=5)
            super().write_image(path, frame, quality)

    w = CaptureSaveWorker(settings=settings, storage=SlowStorage(), outbox_store=RecordingOutbox())
    w.start()
    try:
        w.submit(_job())
        assert mulai_menulis.wait(timeout=5), "penulis tidak pernah mulai"

        # Penulis sedang tertahan di dalam write_image. Submit kedua tetap
        # harus balik seketika, bukan ikut antre di belakangnya.
        t0 = time.monotonic()
        w.submit(_job(timestamp="2026-09-08_091433_000000"))
        assert time.monotonic() - t0 < 0.1, "submit ikut menunggu penulis"
    finally:
        lanjut.set()
        w.stop()


# ---------------------------------------------------------------- hasil tulisan


def test_the_writer_writes_the_same_three_images_and_the_sidecar(worker):
    """Pindah thread tidak boleh mengubah apa yang mendarat di disk."""
    w, storage, outbox = worker

    w.run_once(_job())

    assert len(storage.images) == 2, "bbox + clean"
    assert len(storage.thumbs) == 1
    assert any("/bbox/rej/" in p for p in storage.images)
    assert any("/clean/rej/" in p for p in storage.images)
    (sidecar,) = storage.json
    assert sidecar.endswith("_auto_ripeness.json")


def test_the_sidecar_stays_flat_in_the_day_folder(worker, settings):
    """`BatchUploadWorker._scan()` globs `*/*_ripeness.json` — kedalaman tetap."""
    w, storage, _ = worker

    w.run_once(_job())

    (sidecar,) = storage.json
    relative = str(Path(sidecar).relative_to(settings.results_dir))
    assert relative.count("/") == 1, f"sidecar duduk langsung di folder hari: {relative}"
    assert relative.startswith("2026-09-08/"), "satu level saja: <hari>/<file>.json"


def test_the_writer_enqueues_the_event_for_the_local_api(worker):
    w, _, outbox = worker

    w.run_once(_job())

    [(event_id, _machine, payload)] = outbox.events
    assert payload["event_id"] == event_id
    assert payload["ripeness_status"] == "REJ"
    assert payload["grade_class"] == "Ripe"
    assert "/bbox/rej/" in payload["image_path"]


def test_a_tp_alongside_the_bunch_is_saved_with_the_same_timestamp(worker):
    """TP menempel pada janjang yang memicunya; dua sidecar, satu nama dasar."""
    w, storage, _ = worker

    w.run_once(_job(tp={"tp_status": "PASS", "tp_confidence": 0.8, "bbox": (1, 2, 3, 4)}))

    names = sorted(Path(p).name for p in storage.json)
    assert names == [
        "2026-09-08_091432_123456_auto_ripeness.json",
        "2026-09-08_091432_123456_auto_tp.json",
    ]


# ------------------------------------------------- identitas lahir di depan


def test_the_filename_comes_from_the_job_not_from_the_writers_clock(worker):
    """`event_id` itu uuid5 dari nama file.

    Kalau penulis menghitung ulang jamnya sendiri, id yang dikirim jalur
    realtime tidak lagi sama dengan yang dihitung `BatchUploadWorker` dari nama
    file berjam-jam kemudian — dan idempotensi di sisi API putus: satu janjang
    terhitung dua kali dalam tonase yang dibayar ke petani.
    """
    w, storage, outbox = worker

    w.run_once(_job(timestamp="2026-09-08_091432_123456"))

    assert all("2026-09-08_091432_123456" in p for p in storage.images)
    [(_id, _machine, payload)] = outbox.events

    from palmgrade.domain.vision_event import event_id_for

    assert payload["event_id"] == event_id_for(
        payload["machine_id"], "2026-09-08_091432_123456"
    )


# ------------------------------------------------------------------ kegagalan


def test_a_failed_image_write_keeps_the_sidecar_and_the_event_away(worker):
    """Critical Rule #8 — jangan tinggalkan catatan yang menunjuk file hantu."""
    w, storage, outbox = worker

    def boom(path, frame, quality=80):
        raise OSError("disk penuh")

    storage.write_image = boom

    with pytest.raises(OSError):
        w.run_once(_job())

    assert storage.json == {}, "sidecar yatim: menunjuk gambar yang tidak pernah ada"
    assert outbox.events == []


def test_one_bad_bunch_does_not_kill_the_writer_thread(settings):
    """Satu kegagalan tulis tidak boleh mematikan penulis untuk sisa shift.

    Kalau thread ini mati, tidak ada lagi yang menyimpan bukti — sementara
    deteksi, PLC, dan layar tetap jalan seolah semuanya normal.
    """
    storage = RecordingStorage()
    gagal = {"sekali": True}
    tulis_asli = storage.write_image

    def sekali_gagal(path: Path, frame, quality: int = 80) -> None:
        if gagal["sekali"]:
            gagal["sekali"] = False
            raise OSError("disk penuh")
        tulis_asli(path, frame, quality)

    storage.write_image = sekali_gagal
    w = CaptureSaveWorker(settings=settings, storage=storage, outbox_store=RecordingOutbox())
    w.start()
    try:
        w.submit(_job())
        w.submit(_job(timestamp="2026-09-08_091433_000000"))
        assert w.tunggu_kosong(timeout=5), "antrean tidak pernah selesai"
        assert storage.images, "janjang kedua ikut hilang bersama yang pertama"
    finally:
        w.stop()


# ------------------------------------------------------------------- antrean


def test_a_full_queue_drops_the_newest_and_says_so(settings, caplog):
    """Antrean penuh = penulis kalah cepat dari grading.

    Yang dibuang adalah janjang yang BARU, bukan yang sudah antre: yang lama
    sudah punya pulse PLC terkirim dan urutannya adalah urutan di conveyor.
    Wajib berbunyi di log — bukti yang hilang diam-diam adalah tonase yang
    hilang diam-diam.
    """
    w = CaptureSaveWorker(
        settings=settings,
        storage=RecordingStorage(),
        outbox_store=RecordingOutbox(),
        queue_max=2,
    )
    # Tidak di-start: antrean sengaja dibiarkan menumpuk.
    assert w.submit(_job(timestamp="a")) is True
    assert w.submit(_job(timestamp="b")) is True
    assert w.submit(_job(timestamp="c")) is False, "janjang ketiga harus ditolak, bukan menunggu"
    assert "antrean simpan penuh" in caplog.text.lower()


def test_the_watchdog_can_bring_the_writer_back_after_a_stop(settings):
    """Watchdog 10 detik di `main.py` memanggil `run_loop` langsung, bukan `start()`.

    Penulis yang pernah di-`stop()` lalu dihidupkan lagi lewat jalan itu harus
    benar-benar menulis lagi. Kalau flag berhentinya masih menempel, thread-nya
    hidup dan terlihat sehat di daftar worker — sambil tidak pernah menyimpan
    satu janjang pun.
    """
    storage = RecordingStorage()
    w = CaptureSaveWorker(settings=settings, storage=storage, outbox_store=RecordingOutbox())
    w.start()
    w.stop()

    hidup_lagi = threading.Thread(target=w.run_loop, daemon=True)
    hidup_lagi.start()
    try:
        w.submit(_job())
        assert w.tunggu_kosong(timeout=5), "penulis yang dihidupkan watchdog tetap diam"
        assert storage.images, "hidup tapi tidak menulis apa pun"
    finally:
        w.stop()
        hidup_lagi.join(timeout=2)


def test_the_queue_depth_is_visible(settings):
    """Kedalaman antrean itu alat ukur: kalau naik terus, penulis kalah cepat."""
    w = CaptureSaveWorker(
        settings=settings, storage=RecordingStorage(), outbox_store=RecordingOutbox()
    )
    assert w.antrean == 0
    w.submit(_job())
    assert w.antrean == 1
