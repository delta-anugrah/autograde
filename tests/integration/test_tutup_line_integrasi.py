"""Integrasi tutup line (batch 2.2): penulis bukti, storage, dan `PlcWorker` SUNGGUHAN.

Yang dirangkai tanpa tiruan di tengahnya: `CaptureSaveWorker` dengan
`LocalFileStorage` asli (WebP sungguhan lewat cv2), `PlcWorker` dengan
`PulseScheduler` asli di thread-nya sendiri, `shutdown_plc_worker` asli, dan
`PenutupLine` + `langkah_tutup_line` yang dipakai `main.py`. Yang tiruan cuma
socket PLC (mencatat tulisan coil), kamera, penjadwal R2, dan `os._exit`
(dicatat, bukan dijalankan).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from itertools import count

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

import palmgrade.plc as plc  # noqa: E402
from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.integrations.storage.local_file_storage import LocalFileStorage  # noqa: E402
from palmgrade.plc.pulse import PulseScheduler  # noqa: E402
from palmgrade.plc.worker import PlcWorker  # noqa: E402
from palmgrade.services.langkah_tutup_line import langkah_tutup_line  # noqa: E402
from palmgrade.services.penutup_line import PenutupLine  # noqa: E402
from palmgrade.workers.capture_save_worker import CaptureSaveWorker, SaveJob  # noqa: E402

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
    """Socket PLC tiruan: mencatat tiap tulisan coil ke jejak bersama.

    `jeda_s` meniru link yang mati (tiap panggilan menunggu timeout socket).
    `lepas` memotong jeda itu saat teardown, supaya langkah PLC yang masih
    jalan sesudah tes selesai tidak bocor ke tes berikutnya.
    """

    def __init__(self, jejak: list, *, jeda_s: float = 0.0, lepas: threading.Event) -> None:
        self.jejak = jejak
        self.jeda_s = jeda_s
        self.lepas = lepas

    def write_coil(self, address: int, value: bool) -> bool:
        self.lepas.wait(self.jeda_s)
        self.jejak.append(("coil", address, value))
        return self.jeda_s == 0.0

    def read_discrete_inputs(self, start: int, count: int):
        self.lepas.wait(self.jeda_s)
        return [False] * count

    def close(self) -> None:
        self.jejak.append(("tutup_socket",))


class _DiskLambat(LocalFileStorage):
    """Disk sungguhan, tapi tiap gambar menunggu dulu: antrean benar-benar terisi."""

    def __init__(self, *, jeda_s: float = 0.0, macet: threading.Event | None = None) -> None:
        self.jeda_s = jeda_s
        self.macet = macet

    def write_image(self, path, frame, quality: int = 80) -> None:
        if self.macet is not None:
            self.macet.wait(30)
        time.sleep(self.jeda_s)
        super().write_image(path, frame, quality=quality)


class _Outbox:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    def add_event(self, event_id: str, machine_id: str, payload: dict) -> None:
        self.event_ids.append(event_id)


class _Kamera:
    def __init__(self, jejak: list) -> None:
        self.jejak = jejak

    def disconnect(self) -> None:
        self.jejak.append(("kamera_lepas",))


class _Penjadwal:
    def __init__(self, jejak: list) -> None:
        self.jejak = jejak

    def stop(self, *, tunggu: bool = True) -> None:
        self.jejak.append(("penjadwal_stop", tunggu))


def _job(frame, detik: int, mikro: int = 1) -> SaveJob:
    return SaveJob(
        timestamp=f"2026-09-28_0914{detik:02d}_{mikro:06d}",
        date_folder="2026-09-28",
        truck_folder="091432_B1234XY_a3f9c201",
        annotated_frame=frame,
        clean_frame=frame,
        ripeness_status="acc",
        ripeness_conf=0.9,
        grade_class="Ripe",
        bounding_box={"x_min": 1, "y_min": 2, "x_max": 3, "y_max": 4},
        truck_id="truck-1",
        assignment_id="a3f9c201-dead-beef",
        ffb_source="External",
        event_ts=f"2026-09-28T02:14:{detik:02d}+00:00",
    )


@pytest.fixture
def rakit(tmp_path, monkeypatch):
    """`rakit(storage, socket, batas_s, batas_kuras_s)` → (penutup, penulis, jejak, keluar, settings)."""
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    settings = replace(Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta")
    dibuat: list = []
    lepas_socket = threading.Event()
    sudah_ada = set(threading.enumerate())

    def _rakit(*, storage, socket_jeda_s=0.0, batas_s=5.0, batas_kuras_s=5.0):
        jejak: list = []
        keluar = threading.Event()
        penulis = CaptureSaveWorker(settings=settings, storage=storage, outbox_store=_Outbox())
        t_penulis = threading.Thread(target=penulis.run_loop, daemon=True, name="capture_save")
        t_penulis.start()
        worker = PlcWorker(
            client=_SocketPlc(jejak, jeda_s=socket_jeda_s, lepas=lepas_socket),
            scheduler=PulseScheduler(pulse_s=0.2, gap_s=0.1, queue_max=20),
            settings=_CfgPlc(),
        )
        monkeypatch.setattr(plc, "_worker", worker, raising=False)
        t_plc = threading.Thread(target=worker.run_loop, daemon=True, name="plc")
        t_plc.start()
        worker_threads = [("capture_save", t_penulis, penulis), ("plc", t_plc, worker)]

        def catat_keluar(kode: int) -> None:
            jejak.append(("keluar", kode))
            keluar.set()

        penutup = PenutupLine(batas_s=batas_s, keluar=catat_keluar, tidur=lambda s: None)
        penutup.pasang(
            langkah_tutup_line(
                worker_threads=worker_threads, penulis=penulis, kamera=_Kamera(jejak),
                penjadwal=_Penjadwal(jejak), batas_kuras_s=batas_kuras_s,
            )
        )
        dibuat.append(penulis)
        return penutup, penulis, worker, jejak, keluar

    yield _rakit, settings
    # Langkah tutup yang lewat batas masih jalan sesudah `keluar` (di produksi
    # `os._exit` memotongnya). Tanpa ditunggu, langkah PLC menulis
    # `plc._worker = None` sesudah monkeypatch dipulihkan, di tengah tes lain.
    lepas_socket.set()
    for penulis in dibuat:
        penulis.stop(timeout=1)
    batas = time.monotonic() + 5
    baru = set(threading.enumerate()) - sudah_ada
    for t in baru:
        t.join(timeout=max(0.0, batas - time.monotonic()))
    tertinggal = sorted(t.name for t in baru if t.is_alive())
    assert tertinggal == [], f"thread tutup masih jalan sesudah tes: {tertinggal}"
    assert plc._worker is None


@pytest.fixture
def frame():
    return np.random.default_rng(0).integers(0, 255, (96, 128, 3), dtype=np.uint8)


def test_restart_menulis_semua_janjang_antre_dan_mematikan_coil_sebelum_keluar(rakit, frame):
    _rakit, settings = rakit
    penutup, penulis, worker, jejak, keluar = _rakit(storage=_DiskLambat(jeda_s=0.15))
    worker.submit("acc")  # pulse OK sedang berjalan saat perintah restart datang
    for detik in (1, 2, 3):
        assert penulis.submit(_job(frame, detik))

    penutup.keluar_nanti(0)
    assert keluar.wait(10), "line tidak pernah keluar"

    sidecar = sorted(settings.results_dir.glob("*/*_ripeness.json"))
    assert len(sidecar) == 3, "janjang yang sudah antre hilang saat restart"
    bbox = sorted((settings.results_dir / "2026-09-28").rglob("bbox/**/*.webp"))
    assert len(bbox) == 3 and all(p.stat().st_size > 0 for p in bbox)
    assert len(penulis.outbox_store.event_ids) == 3

    i_keluar = jejak.index(("keluar", 0))
    level_akhir: dict[int, bool] = {}
    for isi in jejak[:i_keluar]:
        if isi[0] == "coil":
            level_akhir[isi[1]] = isi[2]
    assert level_akhir[COIL_OK] is False
    assert all(nilai is False for nilai in level_akhir.values())
    assert ("tutup_socket",) in jejak[:i_keluar]
    assert ("kamera_lepas",) in jejak[:i_keluar]
    assert ("penjadwal_stop", False) in jejak[:i_keluar]
    assert plc._worker is None


def test_disk_macet_keluar_tetap_terjadi_dan_janjang_hilang_disebut(rakit, frame, caplog):
    """Review Focus 1: disk yang macet tidak menahan restart selamanya, dan
    janjang yang tidak sempat ditulis disebut satu per satu."""
    _rakit, settings = rakit
    macet = threading.Event()
    penutup, penulis, _worker, jejak, keluar = _rakit(
        storage=_DiskLambat(macet=macet), batas_s=3.0, batas_kuras_s=0.3
    )
    try:
        penulis.submit(_job(frame, 1))
        penulis.submit(_job(frame, 2))
        mulai = time.monotonic()
        with caplog.at_level(logging.ERROR):
            penutup.keluar_nanti(0)
            assert keluar.wait(10)
        assert time.monotonic() - mulai < 3.5
        assert list(settings.results_dir.glob("*/*_ripeness.json")) == []
    finally:
        macet.set()

    error = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "2 janjang TIDAK tertulis" in error
    assert "2026-09-28_091401_000001" in error and "2026-09-28_091402_000001" in error
    # Coil tetap dimatikan walau disk macet.
    assert any(isi == ("coil", COIL_OK, False) for isi in jejak)


def test_link_plc_mati_tidak_menahan_antrean_simpan(rakit, frame, caplog):
    """Review Focus 2: tiap tulis coil menunggu timeout socket; bukti tetap tertulis,
    dan ERROR batas waktu cuma menyebut `plc`.

    Tes ini TIDAK membuktikan kedua langkah itu serentak: penulis menulis di
    thread-nya sendiri, jadi antrean ini habis juga kalau urutannya berurutan.
    Yang membuktikannya `test_link_plc_mati_dan_disk_macet_janjang_hilang_tetap_disebut`.
    """
    _rakit, settings = rakit
    penutup, penulis, _worker, _jejak, keluar = _rakit(
        storage=_DiskLambat(jeda_s=0.05), socket_jeda_s=0.5, batas_s=1.5
    )
    for detik in (1, 2, 3):
        penulis.submit(_job(frame, detik))

    with caplog.at_level(logging.ERROR):
        penutup.keluar_nanti(0)
        assert keluar.wait(10)

    assert len(list(settings.results_dir.glob("*/*_ripeness.json"))) == 3
    error = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("plc" in m and "antrean_simpan" not in m for m in error)


def test_link_plc_mati_dan_disk_macet_janjang_hilang_tetap_disebut(rakit, frame, caplog):
    """Review Focus 1 + 2 sekaligus: link PLC mati (tahap PLC makan seluruh batas)
    DAN disk macet. Janjang yang hilang tetap disebut satu per satu.

    Ini yang membedakan tahap serentak dari berurutan: kalau antrean baru
    dikuras sesudah PLC selesai, pengurasan tidak pernah mulai sebelum batas
    habis, dan tidak ada yang menyebut janjang yang hilang.
    """
    _rakit, _settings = rakit
    macet = threading.Event()
    penutup, penulis, _worker, _jejak, keluar = _rakit(
        storage=_DiskLambat(macet=macet), socket_jeda_s=1.0, batas_s=3.0, batas_kuras_s=0.3
    )
    try:
        penulis.submit(_job(frame, 1))
        penulis.submit(_job(frame, 2))
        with caplog.at_level(logging.ERROR):
            penutup.keluar_nanti(0)
            assert keluar.wait(10)
    finally:
        macet.set()

    error = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    assert "2 janjang TIDAK tertulis" in error
    assert "2026-09-28_091401_000001 (a3f9c201)" in error
    assert "2026-09-28_091402_000001 (a3f9c201)" in error


def test_janjang_yang_datang_saat_menutup_tertulis_atau_disebut(rakit, frame, caplog):
    """Deteksi tetap jalan selama line menutup (link PLC mati = hampir 9 detik).

    Tiap janjang yang diserahkan sesudah perintah restart harus berakhir di
    salah satu dari dua tempat: tertulis di disk, atau disebut di log ERROR.
    Dulu yang datang sesudah penulis dihentikan diterima (`True`), tidak ditulis
    siapa pun, dan tidak disebut: hilang tanpa jejak.
    """
    _rakit, settings = rakit
    penutup, penulis, _worker, _jejak, keluar = _rakit(
        storage=_DiskLambat(jeda_s=0.02), socket_jeda_s=0.5, batas_s=3.0, batas_kuras_s=0.3
    )
    # Grading lebih lambat dari disk: antrean hampir kosong saat penulis
    # dihentikan, jadi janjang sesudahnya masuk ke celah itu, bukan ditolak
    # karena antrean penuh (yang sudah menyebutnya sendiri).
    diserahkan: list[str] = []
    nomor = count(1)

    def grading() -> None:
        while not keluar.is_set():
            job = _job(frame, 5, next(nomor))
            penulis.submit(job)
            diserahkan.append(job.timestamp)
            time.sleep(0.15)

    with caplog.at_level(logging.ERROR):
        t_grading = threading.Thread(target=grading, daemon=True, name="grading")
        t_grading.start()
        time.sleep(0.2)
        penutup.keluar_nanti(0)
        assert keluar.wait(10)
        t_grading.join(timeout=2)

    tertulis = {p.name.removesuffix("_auto_ripeness.json") for p in settings.results_dir.glob("*/*_ripeness.json")}
    error = " ".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
    hilang_diam = [s for s in diserahkan if s not in tertulis and s not in error]
    assert hilang_diam == [], f"janjang hilang tanpa disebut: {hilang_diam}"
    assert "line sedang menutup" in error, "tidak ada janjang yang datang sesudah pintu ditutup"
