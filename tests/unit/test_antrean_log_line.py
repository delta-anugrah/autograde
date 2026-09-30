"""`AntreanLogLine` + `pasang_log_line` (batch 3.2): log line ke disk tanpa menahan pemanggil."""
from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.domain.log_line import (
    PANJANG_DETAIL_MAKS,
    PANJANG_PESAN_MAKS,
    PANJANG_SUMBER_MAKS,
    EntriLog,
)
from palmgrade.repositories.log_line_repository import NAMA_DB_LOG_LINE, LogLineStore
from palmgrade.services.antrean_log_line import (
    BATAS_BERHENTI_S,
    AntreanLogLine,
    PenulisLogLine,
    pasang_log_line,
    pasang_penulis_log_line,
)

_SRC = Path(__file__).resolve().parents[2] / "src"


class _StoreLambat:
    """Disk yang menahan setiap tulisan sampai dilepas test."""

    def __init__(self) -> None:
        self.lepas = threading.Event()
        self.ditulis: list[EntriLog] = []

    def tulis_banyak(self, entri, *, dibuang_antrean=0) -> None:
        self.lepas.wait(5)
        self.ditulis.extend(entri)


class _StoreRacun:
    """Disk sehat yang menolak satu kejadian tertentu, sendirian maupun dalam satu batch."""

    def __init__(self, racun: str) -> None:
        self.racun = racun
        self.ditulis: list[EntriLog] = []
        self.dibuang = 0

    def tulis_banyak(self, entri, *, dibuang_antrean=0) -> None:
        entri = list(entri)
        if any(e.message == self.racun for e in entri):
            raise ValueError("kejadian ini tidak bisa disimpan")
        self.ditulis.extend(entri)
        self.dibuang += dibuang_antrean


class _StoreRusak:
    def __init__(self) -> None:
        self.rusak = True
        self.ditulis: list[EntriLog] = []
        self.dibuang = 0

    def tulis_banyak(self, entri, *, dibuang_antrean=0) -> None:
        if self.rusak:
            raise OSError("disk penuh")
        self.ditulis.extend(entri)
        self.dibuang += dibuang_antrean


def test_write_tidak_menunggu_disk_yang_lambat():
    """Aturan 1b: thread deteksi yang menulis ERROR tidak boleh ikut menunggu disk."""
    store = _StoreLambat()
    antrean = AntreanLogLine(store, jeda_s=0.0)
    berhenti = antrean.mulai()
    try:
        antrean.write("ERROR", "a", "pertama", None, now=1.0)
        time.sleep(0.2)  # penulis sudah menahan tulisan pertama
        mulai = time.perf_counter()
        for i in range(100):
            antrean.write("ERROR", "a", f"pesan {i}", None, now=2.0)
        assert time.perf_counter() - mulai < 0.1
    finally:
        store.lepas.set()
        berhenti.set()


def test_kuras_menulis_semua_yang_menunggu_dalam_satu_panggilan(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    antrean = AntreanLogLine(store)
    antrean.write("ERROR", "a", "satu", None, now=1.0)
    antrean.write("WARNING", "b", "dua", "tb", now=2.0)

    assert antrean.kuras() == 2
    assert antrean.kuras() == 0
    hasil = store.ambil(setelah=0, generasi=store.generasi, batas=10)
    assert [e["message"] for e in hasil["entri"]] == ["satu", "dua"]


def test_antrean_penuh_membuang_yang_paling_lama_dan_menghitungnya(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    antrean = AntreanLogLine(store, kapasitas=3)
    for i in range(5):
        antrean.write("ERROR", "a", f"pesan {i}", None, now=float(i * 100))

    antrean.kuras()

    hasil = store.ambil(setelah=0, generasi=store.generasi, batas=10)
    assert [e["message"] for e in hasil["entri"]] == ["pesan 2", "pesan 3", "pesan 4"]
    assert hasil["dibuang"] == 2


def test_disk_rusak_tidak_melempar_dan_kejadian_menunggu_giliran_berikut(capsys):
    store = _StoreRusak()
    antrean = AntreanLogLine(store)
    antrean.write("ERROR", "a", "satu", None, now=1.0)

    assert antrean.kuras() == 0
    antrean.write("ERROR", "a", "dua", None, now=2.0)
    assert antrean.kuras() == 0
    store.rusak = False
    assert antrean.kuras() == 2

    assert [e.message for e in store.ditulis] == ["satu", "dua"]
    # Mengeluh sekali saja, bukan tiap kurasan, dan menyebut sebabnya.
    err = capsys.readouterr().err
    assert err.count("log line could not be written") == 1
    assert "OSError: disk penuh" in err


def test_gangguan_disk_kedua_dikeluhkan_lagi(capsys):
    """Sesudah pulih, gangguan berikutnya tidak boleh diam: itu kejadian baru."""
    store = _StoreRusak()
    antrean = AntreanLogLine(store)
    antrean.write("ERROR", "a", "satu", None, now=1.0)
    antrean.kuras()
    store.rusak = False
    antrean.kuras()
    store.rusak = True
    antrean.write("ERROR", "a", "dua", None, now=2.0)
    antrean.kuras()

    assert capsys.readouterr().err.count("log line could not be written") == 2


@pytest.mark.parametrize(
    "stderr_rusak",
    [pytest.param("tertutup", id="stderr-tertutup"), pytest.param("oserror", id="stderr-oserror")],
)
def test_stderr_rusak_tidak_mematikan_penulis(monkeypatch, stderr_rusak):
    class _StderrOsError(io.StringIO):
        def write(self, _teks):
            raise OSError("stderr hilang")

    if stderr_rusak == "tertutup":
        tertutup = io.StringIO()
        tertutup.close()
        monkeypatch.setattr(sys, "stderr", tertutup)
    else:
        monkeypatch.setattr(sys, "stderr", _StderrOsError())
    antrean = AntreanLogLine(_StoreRusak())
    antrean.write("ERROR", "a", "satu", None, now=1.0)

    assert antrean.kuras() == 0


def test_satu_kejadian_racun_tidak_menyandera_yang_lain():
    """Batch gagal: tulis satu per satu, buang dan hitung yang gagal sendirian."""
    store = _StoreRacun("racun")
    antrean = AntreanLogLine(store)
    antrean.write("WARNING", "a", "racun", None, now=1.0)
    antrean.write("ERROR", "a", "baik", None, now=2.0)

    assert antrean.kuras() == 1
    assert [e.message for e in store.ditulis] == ["baik"]
    assert store.dibuang == 1
    assert antrean.kuras() == 0


def test_teks_surrogate_disimpan_aman_dan_tidak_menahan_kejadian_berikut(tmp_path):
    """Nama berkas yang bukan UTF-8 (`\\udcff`) tidak bisa di-encode SQLite apa adanya."""
    store = LogLineStore(tmp_path / "log_line.db")
    antrean = AntreanLogLine(store)
    antrean.write("WARNING", "a\udcff", "file \udcff bad", "tb \udcff", now=1.0)
    antrean.write("ERROR", "a", "good one", None, now=2.0)

    assert antrean.kuras() == 2
    entri = store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"]
    assert [e["message"] for e in entri] == ["file \\udcff bad", "good one"]
    assert entri[0]["source"] == "a\\udcff"
    assert entri[0]["detail"] == "tb \\udcff"


def test_write_memotong_sebelum_antre_supaya_memori_terbatas():
    store = _StoreRusak()
    store.rusak = False
    antrean = AntreanLogLine(store)
    antrean.write("ERROR", "s" * 5000, "m" * 50_000, "d" * 50_000, now=1.0)
    antrean.kuras()

    (e,) = store.ditulis
    assert len(e.source) == PANJANG_SUMBER_MAKS
    assert len(e.message) == PANJANG_PESAN_MAKS
    assert len(e.detail) == PANJANG_DETAIL_MAKS


def test_write_dari_thread_yang_sama_saat_kunci_dipegang_tidak_macet():
    """Finalizer atau signal handler yang menulis log di tengah `write()` thread yang sama."""
    antrean = AntreanLogLine(_StoreRusak())

    def tulis_bersarang() -> None:
        with antrean._kunci:
            antrean.write("ERROR", "a", "bersarang", None, now=1.0)

    t = threading.Thread(target=tulis_bersarang, daemon=True)
    t.start()
    t.join(2)
    assert not t.is_alive()


def test_disk_rusak_lama_tetap_dibatasi_kapasitas():
    store = _StoreRusak()
    antrean = AntreanLogLine(store, kapasitas=2)
    for i in range(5):
        antrean.write("ERROR", "a", f"p{i}", None, now=float(i))
        antrean.kuras()
    store.rusak = False
    antrean.kuras()

    assert [e.message for e in store.ditulis] == ["p3", "p4"]
    assert store.dibuang == 3


def test_thread_penulis_menguras_sendiri(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    antrean = AntreanLogLine(store, jeda_s=0.0)
    berhenti = antrean.mulai()
    try:
        antrean.write("ERROR", "a", "sampai sendiri", None, now=1.0)
        batas = time.time() + 3
        while time.time() < batas:
            if store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"]:
                break
            time.sleep(0.02)
        assert store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"][0]["message"] == "sampai sendiri"
    finally:
        berhenti.set()


def test_berhenti_menguras_sisa_terakhir(tmp_path):
    store = LogLineStore(tmp_path / "log_line.db")
    antrean = AntreanLogLine(store, jeda_s=5.0)
    berhenti = threading.Event()
    berhenti.set()
    antrean.write("ERROR", "a", "sisa", None, now=1.0)

    antrean.jalan(berhenti)

    assert store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"][0]["message"] == "sisa"


def test_lewat_handler_asli_tersaring_redaksi_dan_level(tmp_path):
    """Handler yang dipasang di line adalah `SqliteLogHandler` yang sama dengan konsol."""
    store = LogLineStore(tmp_path / "log_line.db")
    antrean = AntreanLogLine(store)
    log = logging.getLogger("uji.antrean_log_line")
    log.handlers.clear()
    log.propagate = False
    log.setLevel(logging.DEBUG)
    log.addHandler(SqliteLogHandler(antrean))
    log.info("tidak disimpan")
    log.warning("token=rahasia-sekali bocor?")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        log.exception("grab gagal")
    log.critical("mati total")
    antrean.kuras()

    entri = store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"]
    assert [(e["level"], e["message"]) for e in entri] == [
        ("WARNING", "token=«redacted» bocor?"),
        ("ERROR", "grab gagal"),
        ("ERROR", "mati total"),
    ]
    assert "RuntimeError: boom" in entri[1]["detail"]


def test_pasang_log_line_memasang_handler_di_root(tmp_path):
    root = logging.getLogger()
    sebelum = list(root.handlers)
    penulis = pasang_penulis_log_line(tmp_path)
    assert penulis is not None
    try:
        store = penulis.store
        assert (tmp_path / NAMA_DB_LOG_LINE).exists()
        baru = [h for h in root.handlers if h not in sebelum]
        assert len(baru) == 1 and isinstance(baru[0], SqliteLogHandler)
        logging.getLogger("uji.pasang").error("dari root")
        batas = time.time() + 3
        while time.time() < batas and not store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"]:
            time.sleep(0.02)
        pesan = [e["message"] for e in store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"]]
        assert "dari root" in pesan
    finally:
        assert penulis.hentikan() is True
    assert list(root.handlers) == sebelum


def test_hentikan_menulis_sisa_yang_belum_dikuras(tmp_path):
    root = logging.getLogger()
    sebelum = list(root.handlers)
    penulis = pasang_penulis_log_line(tmp_path)
    assert penulis is not None
    try:
        penulis.antrean.write("ERROR", "a", "tepat sebelum berhenti", None, now=1.0)
    finally:
        penulis.hentikan()
    store = penulis.store
    assert [e["message"] for e in store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"]] == [
        "tepat sebelum berhenti"
    ]
    assert list(root.handlers) == sebelum


def test_hentikan_tidak_menunggu_disk_yang_macet():
    """Dipanggil tepat sebelum `os._exit` (restart dari konsol): disk log yang macet
    tidak boleh menahan restart lebih dari `BATAS_BERHENTI_S`."""
    store = _StoreLambat()
    antrean = AntreanLogLine(store, jeda_s=0.0)
    penulis = PenulisLogLine(store, antrean, SqliteLogHandler(antrean), antrean.mulai())
    try:
        antrean.write("ERROR", "a", "tertahan di disk", None, now=1.0)
        time.sleep(0.2)  # penulis sudah masuk tulis_banyak dan tertahan
        mulai = time.monotonic()
        assert penulis.hentikan() is False
        assert time.monotonic() - mulai < BATAS_BERHENTI_S + 0.3
    finally:
        store.lepas.set()


def test_galat_startup_lalu_keluar_tetap_tertulis(tmp_path):
    """Line yang gagal start lalu `sys.exit`: justru kejadian ini yang dicari support."""
    skrip = (
        "import logging, sys\n"
        "from pathlib import Path\n"
        "from palmgrade.services.antrean_log_line import pasang_log_line\n"
        "pasang_log_line(Path(sys.argv[1]))\n"
        "logging.getLogger('uvicorn.error').error('Application startup failed. Exiting.')\n"
        "sys.exit(3)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(_SRC)}
    hasil = subprocess.run(
        [sys.executable, "-c", skrip, str(tmp_path)], env=env, capture_output=True, text=True, timeout=60
    )

    assert hasil.returncode == 3, hasil.stderr
    store = LogLineStore(tmp_path / NAMA_DB_LOG_LINE)
    entri = store.ambil(setelah=0, generasi=store.generasi, batas=10)["entri"]
    assert [(e["level"], e["source"], e["message"]) for e in entri] == [
        ("ERROR", "uvicorn.error", "Application startup failed. Exiting.")
    ]


def test_pasang_log_line_gagal_membuka_mengembalikan_none_tanpa_melempar(tmp_path):
    """Folder DB yang ternyata berkas biasa: line tetap start, cuma tanpa log di disk."""
    bukan_folder = tmp_path / "state"
    bukan_folder.write_text("bukan folder")
    root = logging.getLogger()
    sebelum = list(root.handlers)

    assert pasang_log_line(bukan_folder) is None
    assert list(root.handlers) == sebelum
