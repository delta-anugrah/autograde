"""Camera commands from a request, run by the capture thread between two grabs (rule 3)."""
from __future__ import annotations

import threading
import time

import pytest
from ai_palsu import LinePalsu

from palmgrade.workers.perintah_kamera import AntreanPerintahKamera, KameraTidakMenjawab


def _layani_sekali_nanti(antrean: AntreanPerintahKamera, kunci: threading.Lock, jeda: float = 0.05) -> None:
    def _jalan() -> None:
        time.sleep(jeda)
        antrean.jalankan(kunci)
    threading.Thread(target=_jalan, daemon=True).start()


def test_hasil_kembali_ke_peminta():
    antrean, kunci = AntreanPerintahKamera(), threading.Lock()
    _layani_sekali_nanti(antrean, kunci)
    assert antrean.minta(lambda: 42, batas_detik=2.0) == 42


def test_dijalankan_di_bawah_kunci_kamera():
    antrean, kunci = AntreanPerintahKamera(), threading.Lock()
    _layani_sekali_nanti(antrean, kunci)
    assert antrean.minta(kunci.locked, batas_detik=2.0) is True


def test_galat_perintah_sampai_ke_peminta():
    antrean, kunci = AntreanPerintahKamera(), threading.Lock()
    _layani_sekali_nanti(antrean, kunci)

    def _gagal():
        raise RuntimeError("camera not connected")

    with pytest.raises(RuntimeError, match="not connected"):
        antrean.minta(_gagal, batas_detik=2.0)


def test_tidak_dilayani_habis_waktu():
    with pytest.raises(KameraTidakMenjawab):
        AntreanPerintahKamera().minta(lambda: 1, batas_detik=0.05)


def test_perintah_yang_sudah_ditinggal_tidak_dijalankan_belakangan():
    """Review Focus 5: once the route gave up, the camera must not see the command (phase 2 writes)."""
    antrean, kunci = AntreanPerintahKamera(), threading.Lock()
    dijalankan = []
    with pytest.raises(KameraTidakMenjawab):
        antrean.minta(lambda: dijalankan.append(1), batas_detik=0.05)
    assert antrean.jalankan(kunci) == 0
    assert dijalankan == []


def test_antrean_kosong_tidak_menunggu():
    assert AntreanPerintahKamera().jalankan(threading.Lock()) == 0


def test_capture_worker_melayani_antrean_tiap_putaran():
    line = LinePalsu()
    hasil = {}

    def _minta() -> None:
        hasil["x"] = line.state.perintah_kamera.minta(lambda: "dibaca", batas_detik=2.0)

    peminta = threading.Thread(target=_minta)
    peminta.start()
    time.sleep(0.05)
    line.jalan(1)
    peminta.join(timeout=2)
    assert hasil == {"x": "dibaca"}
