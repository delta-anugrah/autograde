"""`AntreanLogLine` + `pasang_log_line` (batch 3.2): log line ke disk tanpa menahan pemanggil."""
from __future__ import annotations

import logging
import threading
import time

from palmgrade.core.log_sink import SqliteLogHandler
from palmgrade.domain.log_line import EntriLog
from palmgrade.repositories.log_line_repository import NAMA_DB_LOG_LINE, LogLineStore
from palmgrade.services.antrean_log_line import AntreanLogLine, pasang_log_line


class _StoreLambat:
    """Disk yang menahan setiap tulisan sampai dilepas test."""

    def __init__(self) -> None:
        self.lepas = threading.Event()
        self.ditulis: list[EntriLog] = []

    def tulis_banyak(self, entri, *, dibuang_antrean=0) -> None:
        self.lepas.wait(5)
        self.ditulis.extend(entri)


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
    # Mengeluh sekali saja, bukan tiap kurasan.
    assert capsys.readouterr().err.count("log line could not be written") == 1


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
    try:
        store = pasang_log_line(tmp_path)
        assert store is not None
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
        for h in [h for h in root.handlers if h not in sebelum]:
            root.removeHandler(h)


def test_pasang_log_line_gagal_membuka_mengembalikan_none_tanpa_melempar(tmp_path):
    """Folder DB yang ternyata berkas biasa: line tetap start, cuma tanpa log di disk."""
    bukan_folder = tmp_path / "state"
    bukan_folder.write_text("bukan folder")
    root = logging.getLogger()
    sebelum = list(root.handlers)

    assert pasang_log_line(bukan_folder) is None
    assert list(root.handlers) == sebelum
