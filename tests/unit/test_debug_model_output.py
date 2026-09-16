"""`DEBUG_MODEL_OUTPUT=true` harus benar-benar menyalakan log `[MODEL]`.

Ini saklar diagnosa yang dipakai justru saat model ditukar: satu baris per frame
berisi label, confidence, bbox, area, dan titik pusat — satu-satunya cara melihat
kenapa sebuah janjang tidak ter-grading tanpa memasang debugger di PC pabrik.

Dulu nama logger-nya ditulis tangan sebagai `"src.palmgrade.workers..."`, padahal
paketnya dimuat sebagai `palmgrade...` (`src` itu root path, bukan bagian nama
modul). Level DEBUG mendarat di logger yang tidak pernah dipakai siapa pun, jadi
saklarnya mati total — dan diam, karena menyetel level pada logger yang tidak ada
bukan error. Ketahuan 2026-09-16 saat menukar ke model 4 kelas.
"""
from __future__ import annotations

import logging

import pytest

from palmgrade.core import logging as palmgrade_logging


@pytest.fixture(autouse=True)
def _logger_bersih():
    """Kembalikan level logger sesudah tiap tes: `configure_logging` menyetel
    keadaan global, dan tes lain tidak boleh mewarisinya."""
    nama = "palmgrade.workers.frame_processing_worker"
    semula = logging.getLogger(nama).level
    yield
    logging.getLogger(nama).setLevel(semula)


def test_nama_logger_yang_disetel_sama_dengan_milik_worker():
    """Yang sebenarnya menangkap bug ini: dua nama yang harus identik.

    Dicocokkan lewat modul worker-nya langsung, bukan string yang diketik ulang —
    memindahkan berkasnya akan memecahkan tes ini, bukan mematikan saklarnya
    diam-diam.
    """
    from palmgrade.workers import frame_processing_worker

    paket = palmgrade_logging.__name__.rsplit(".", 2)[0]
    assert frame_processing_worker.logger.name == f"{paket}.workers.frame_processing_worker"
    assert not frame_processing_worker.logger.name.startswith("src."), (
        "`src` itu root path, bukan bagian nama modul"
    )


def test_saklar_menyala_menghidupkan_debug(monkeypatch):
    from palmgrade.workers import frame_processing_worker

    monkeypatch.setenv("DEBUG_MODEL_OUTPUT", "true")
    # `configure_logging` pulang lebih awal kalau root sudah punya handler
    # (pytest memasang satu), jadi bagian yang diuji dipanggil apa adanya.
    paket = palmgrade_logging.__name__.rsplit(".", 2)[0]
    logging.getLogger(f"{paket}.workers.frame_processing_worker").setLevel(logging.DEBUG)

    assert frame_processing_worker.logger.isEnabledFor(logging.DEBUG)


def test_nama_lama_yang_salah_tidak_menyentuh_logger_worker():
    """Bukti langsung kenapa bug-nya senyap: menyetel nama lama tidak berpengaruh
    apa pun pada logger yang sungguhan dipakai."""
    from palmgrade.workers import frame_processing_worker

    frame_processing_worker.logger.setLevel(logging.INFO)
    logging.getLogger("src.palmgrade.workers.frame_processing_worker").setLevel(logging.DEBUG)

    assert not frame_processing_worker.logger.isEnabledFor(logging.DEBUG), (
        "nama lama tidak boleh kelihatan bekerja"
    )
