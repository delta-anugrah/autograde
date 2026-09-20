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
    assert any("/bbox/Ripe/" in p for p in storage.images)
    assert any("/clean/Ripe/" in p for p in storage.images)
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
    assert "/bbox/Ripe/" in payload["image_path"]


def test_tp_menumpang_di_sidecar_janjangnya_bukan_berkas_kedua(worker):
    """Satu janjang = satu sidecar, TP atau tidak (2026-09-20).

    Dulu TP jadi `_auto_tp.json` terpisah, dan memasangkannya kembali butuh tiga
    blok khusus di `BatchUploadWorker` plus satu kelas galat untuk TP yatim —
    sidecar TP yang pasangannya tidak ada tidak bisa dikirim sama sekali.
    """
    w, storage, _ = worker

    w.run_once(_job(
        grade_class="Ripe",
        tp={"tp_status": True, "tp_confidence": 0.8, "bbox": (5, 6, 7, 8)},
    ))

    names = sorted(Path(p).name for p in storage.json)
    assert names == ["2026-09-08_091432_123456_auto_ripeness.json"]

    (meta,) = storage.json.values()
    assert meta["tp_status"] is True
    assert meta["tp_confidence"] == 0.8
    assert meta["tp_bounding_box"] == {"x_min": 5, "y_min": 6, "x_max": 7, "y_max": 8}
    # Kotak janjangnya sendiri tidak boleh tertimpa kotak tangkainya.
    assert meta["bounding_box"] == {"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4}


def test_janjang_tanpa_tp_tetap_membawa_ketiga_field_tp(worker):
    """Field-nya selalu ada, isinya yang kosong.

    Pembaca sidecar tidak boleh perlu bertanya "field-nya ada tidak ya" — yang
    kadang ada kadang tidak memaksa tiap pembaca berjaga sendiri, dan cepat atau
    lambat ada satu yang lupa.
    """
    w, storage, _ = worker

    w.run_once(_job())

    (meta,) = storage.json.values()
    assert meta["tp_status"] is False
    assert meta["tp_confidence"] == 0
    assert meta["tp_bounding_box"] is None


def test_ripe_bertangkai_panjang_difiling_di_subfolder_tp(worker):
    """Mencari hasil TP = membuka satu folder."""
    w, storage, _ = worker

    w.run_once(_job(
        grade_class="Ripe",
        tp={"tp_status": True, "tp_confidence": 0.9, "bbox": (1, 1, 2, 2)},
    ))

    assert any("/bbox/Ripe/TP/" in p for p in storage.images)
    assert any("/clean/Ripe/TP/" in p for p in storage.images)
    (thumb,) = storage.thumbs
    assert "/thumb/Ripe/TP/" in thumb
    # Tautan yang dikirim ke layar harus menunjuk berkas yang benar-benar ditulis.
    (meta,) = storage.json.values()
    assert "/bbox/Ripe/TP/" in meta["image_path"]


def test_machine_id_ikut_di_sidecar(worker, settings):
    """Tiga line menulis ke pohon yang sama; tanpa ini foto satu line tidak bisa
    dipisahkan dari line lain tanpa membuka basis data.

    `machine_id`, bukan `line_code`: proses line cuma mengenal id mesinnya
    sendiri, dan pemetaan ke `line-1`/`line-2` hidup di konsol. Menulis kode line
    di sini berarti membuat pemetaan kedua yang bisa berbeda dari yang dipakai
    mengelompokkan rekap.
    """
    w, storage, _ = worker

    w.run_once(_job())

    (meta,) = storage.json.values()
    assert meta["machine_id"] == settings.machine_id


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


def test_the_default_queue_holds_a_realistic_burst_without_hoarding_ram(settings):
    """Kedalaman bawaan itu kompromi dua angka terukur, bukan angka bulat.

    Dari bawah: beban nyata 300 janjang/jam/line (`spek-pc-pabrik`) = satu tiap
    12 detik, sementara penulis butuh ~0,6 detik — jadi antrean ini untuk
    lonjakan, dan terlalu dangkal berarti bukti hilang saat beberapa janjang
    lewat ROI beruntun.
    Dari atas: tiap job menahan DUA frame 2448x2048 (28,7 MB), jadi 3 line x 8
    = 689 MB dari RAM 31 GB. Puluhan dalam mulai berarti buat RAM sekaligus cuma
    menunda kabar buruk.
    """
    w = CaptureSaveWorker(
        settings=settings, storage=RecordingStorage(), outbox_store=RecordingOutbox()
    )
    assert w._queue.maxsize == 8

    megabyte_per_job = 2 * 2448 * 2048 * 3 / 1024 / 1024
    tiga_line = 3 * w._queue.maxsize * megabyte_per_job
    assert tiga_line < 1024, f"tiga line menahan {tiga_line:.0f} MB frame di antrean"


def test_the_queue_depth_is_visible(settings):
    """Kedalaman antrean itu alat ukur: kalau naik terus, penulis kalah cepat."""
    w = CaptureSaveWorker(
        settings=settings, storage=RecordingStorage(), outbox_store=RecordingOutbox()
    )
    assert w.antrean == 0
    w.submit(_job())
    assert w.antrean == 1


def test_dropped_bunches_are_counted_not_only_logged(settings):
    """Bukti yang hilang harus punya ANGKA, bukan cuma satu baris log.

    Janjang yang dibuang sudah menerima pulse PLC (buahnya sudah disortir) dan
    sudah masuk hitungan di layar, tapi tidak akan punya gambar maupun sidecar —
    jadi `BatchUploadWorker._scan()` tidak akan pernah menemukannya, sekarang
    maupun nanti. PC pabrik cuma dijenguk lewat AnyDesk dan log-nya bergulir;
    angka di `/health/detail` adalah satu-satunya cara ini kelihatan.
    """
    w = CaptureSaveWorker(
        settings=settings,
        storage=RecordingStorage(),
        outbox_store=RecordingOutbox(),
        queue_max=1,
    )
    assert w.dibuang == 0
    w.submit(_job(timestamp="a"))
    w.submit(_job(timestamp="b"))
    w.submit(_job(timestamp="c"))
    assert w.dibuang == 2


def test_health_detail_can_carry_the_two_numbers(settings):
    """Skema `/health/detail` harus punya tempat untuk keduanya.

    Angkanya percuma kalau `HealthDetailSchema` membuangnya diam-diam — Pydantic
    tidak akan mengeluh, dan yang terlihat cuma endpoint yang tidak pernah
    menyebut janjang yang hilang. `HealthService` sendiri mengimpor torch, jadi
    yang diuji di CI ringan adalah kontrak datanya (CLAUDE.md § Tests).
    """
    from palmgrade.schemas.common_schema import HealthDetailSchema

    payload = HealthDetailSchema(
        status="ok", environment="production", version="v1",
        camera_type="hikrobot", camera_connected=True,
        gpu_available=True, gpu_device="RTX 3060",
        machine_id="m", workers=[],
        outbox_pending=0, outbox_failed=0,
        capture_save_pending=2, capture_save_dropped=7,
    )

    assert payload.capture_save_pending == 2
    assert payload.capture_save_dropped == 7
    # Bawaannya nol, supaya konsol (yang tidak punya penulis) tetap sah.
    kosong = HealthDetailSchema(
        status="ok", environment="production", version="v1",
        camera_type="hikrobot", camera_connected=True,
        gpu_available=False, gpu_device=None, machine_id="m", workers=[],
    )
    assert kosong.capture_save_dropped == 0


def test_stop_waits_for_a_thread_it_did_not_start_itself(settings):
    """`main.py` menjalankan `run_loop` lewat `_start_worker`, bukan `start()`.

    Jadi `_thread` kosong di produksi. `stop()` yang cuma menunggu `_thread`
    akan balik seketika di satu-satunya tempat yang benar-benar memakainya —
    dan tenggang itu terlewat justru saat penulis sedang tersendat, yaitu saat
    tenggangnya berguna.
    """
    import threading as th

    w = CaptureSaveWorker(
        settings=settings, storage=RecordingStorage(), outbox_store=RecordingOutbox()
    )
    # Persis seperti main.py: thread dibuat di luar, dinamai sama.
    t = th.Thread(target=w.run_loop, daemon=True, name="capture_save")
    t.start()
    # Beri loop kesempatan benar-benar masuk.
    assert w.tunggu_kosong(timeout=5)

    w.stop(timeout=5)

    assert not t.is_alive(), "stop() balik sebelum penulis benar-benar keluar"


# ------------------------------------------- penghitung TP telat + mode dev


def test_health_detail_membawa_hitungan_tp_telat():
    """`tp_telat` di `/health/detail` = TP yang muncul sesudah janjangnya difoto.

    Janjang difoto apa adanya begitu menyentuh garis (keputusan operator
    2026-09-18), jadi tangkai yang telat memang tidak ikut. Angkanya diekspos
    supaya keputusan menambah jendela tunggu nanti diambil dari data Lampung,
    bukan dari dugaan — dan PC pabrik cuma dijenguk lewat AnyDesk, jadi satu
    baris log saja tidak akan pernah terbaca.
    """
    from palmgrade.schemas.common_schema import HealthDetailSchema

    payload = HealthDetailSchema(
        status="ok", environment="production", version="v1",
        camera_type="hikrobot", camera_connected=True,
        gpu_available=True, gpu_device="RTX 3060",
        machine_id="m", workers=[], tp_telat=3,
    )
    assert payload.tp_telat == 3
    # Bawaannya nol: konsol tidak punya jalur deteksi sama sekali.
    assert HealthDetailSchema(
        status="ok", environment="production", version="v1",
        camera_type="hikrobot", camera_connected=True,
        gpu_available=False, gpu_device=None, machine_id="m", workers=[],
    ).tp_telat == 0


def test_mode_dev_ikut_jalur_setelan_yang_sama():
    """Toggle dev menumpang mekanisme `CONF_THRESHOLD`, bukan mekanisme baru.

    Bawaannya MATI: angka confidence di layar operator terbaca seperti mutu
    buah dari jarak beberapa meter, dan itu yang membuatnya dibuang 2026-09-18.
    Yang butuh angka itu support yang sedang menyetel ambang.
    """
    from palmgrade.domain.setelan_grading import bersihkan_setelan

    assert bersihkan_setelan(
        {"conf_threshold": 0.5, "minimum_size": 3000}
    )["mode_dev"] is False

    assert bersihkan_setelan(
        {"conf_threshold": 0.5, "minimum_size": 3000, "mode_dev": True}
    )["mode_dev"] is True


def test_mode_dev_menerima_bentuk_yang_dikirim_layar_maupun_konsol_lama():
    """Input HTML dan konsol versi lain tidak seragam mengirim boolean."""
    from palmgrade.domain.setelan_grading import bersihkan_setelan

    for dikirim, diharapkan in (("true", True), ("false", False), (1, True), (0, False)):
        bersih = bersihkan_setelan(
            {"conf_threshold": 0.5, "minimum_size": 3000, "mode_dev": dikirim}
        )
        assert bersih["mode_dev"] is diharapkan, f"{dikirim!r} dibaca salah"
