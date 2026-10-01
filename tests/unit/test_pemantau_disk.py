"""`PemantauDisk` (batch 3.7): ukur partisi → satu blok `disk`, tanpa R2.

Aturannya diuji di `test_kesehatan_disk.py`; di sini perakitannya: partisi yang
diukur, tingkat terakhir yang diingat (histeresis, jam `sejak`), log sekali per
transisi, dan tidak pernah melempar walau disk tak terbaca.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from collections import namedtuple
from dataclasses import replace
from pathlib import Path

from palmgrade.core.config import Settings
from palmgrade.domain.kesehatan_disk import GB
from palmgrade.services.pemantau_disk import PemantauDisk, ringkas_disk_dari_state
from palmgrade.workers.runtime_state import RuntimeState

Usage = namedtuple("Usage", "total used free")
LINE_2 = "a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02"


class DiskPalsu:
    def __init__(self, bebas_gb: float, total_gb: float = 468) -> None:
        self.bebas_gb = bebas_gb
        self.total_gb = total_gb
        self.diukur: list[Path] = []
        self.rusak = False

    def __call__(self, jalur: Path) -> Usage:
        self.diukur.append(jalur)
        if self.rusak:
            raise OSError("statvfs gagal")
        total, bebas = int(self.total_gb * GB), int(self.bebas_gb * GB)
        return Usage(total, total - bebas, bebas)


def _rakit(disk: DiskPalsu, **ubah) -> PemantauDisk:
    settings = replace(Settings(), **{"machine_id": LINE_2, "disk_peringatan_gb": 15.0,
                                      "disk_kritis_gb": 5.0, "r2_bucket": "", **ubah})
    return PemantauDisk(settings=settings, jalur=(Path("/app/artifacts"), Path("/app/state")),
                        ukur=disk, jam_dinding=lambda: 1_790_000_000.0)


def test_disk_lega_aman_tanpa_r2():
    kawat = _rakit(DiskPalsu(232)).ringkas()
    assert (kawat["tingkat"], kawat["kode"], kawat["bebas_gb"], kawat["sejak"]) == ("aman", None, 232.0, None)


def test_mengukur_kedua_partisi_dan_jalur_kembar_sekali():
    disk = DiskPalsu(232)
    pemantau = PemantauDisk(settings=replace(Settings(), r2_bucket=""),
                            jalur=(Path("/a"), Path("/b"), Path("/a")), ukur=disk)
    pemantau.ringkas()
    assert disk.diukur == [Path("/a"), Path("/b")]


def test_peringatan_membawa_kode_dan_jam_mulai():
    kawat = _rakit(DiskPalsu(12)).ringkas()
    assert (kawat["tingkat"], kawat["kode"], kawat["sejak"]) == (
        "peringatan", "DISK_HAMPIR_PENUH", 1_790_000_000.0
    )


def test_histeresis_diingat_antar_panggilan():
    disk = DiskPalsu(14)
    pemantau = _rakit(disk)
    assert pemantau.ringkas()["tingkat"] == "peringatan"
    disk.bebas_gb = 15.5                       # retensi membuang sedikit: belum lega
    assert pemantau.ringkas()["tingkat"] == "peringatan"
    disk.bebas_gb = 16.5
    assert pemantau.ringkas()["tingkat"] == "aman"


def test_disk_tak_terbaca_tidak_melempar():
    disk = DiskPalsu(232)
    disk.rusak = True
    kawat = _rakit(disk).ringkas()
    assert (kawat["tingkat"], kawat["bebas_gb"]) == ("tidak_terbaca", None)


def test_transisi_dicatat_sekali_masing_masing(caplog):
    caplog.set_level(logging.WARNING, logger="palmgrade.services.pemantau_disk")
    disk = DiskPalsu(232)
    pemantau = _rakit(disk)
    for bebas in (232, 14, 14, 13, 4, 4, 3, 30, 30):
        disk.bebas_gb = bebas
        pemantau.ringkas()
    pesan = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert [lvl for lvl, _ in pesan] == ["WARNING", "ERROR", "WARNING"]
    assert "line-2" in pesan[0][1] and "DISK_HAMPIR_PENUH" in pesan[0][1] and "sisa 14.0 GB" in pesan[0][1]
    assert "DISK_KRITIS" in pesan[1][1] and "docker system prune" in pesan[1][1]
    assert pesan[2][1] == "Disk line-2 kembali lega: sisa 30.0 GB"


def test_peringatan_setinggi_lantai_r2_diperingatkan_saat_start(caplog):
    caplog.set_level(logging.WARNING, logger="palmgrade.services.pemantau_disk")
    _rakit(DiskPalsu(232), r2_bucket="palmgrade-captures", disk_peringatan_gb=25.0,
           upload_disk_min_free_gb=20.0)
    assert any("menyala terus" in r.getMessage() for r in caplog.records)


def test_ringkas_dari_state():
    state = RuntimeState()
    assert ringkas_disk_dari_state(state) is None
    assert ringkas_disk_dari_state(None) is None
    state.pemantau_disk = _rakit(DiskPalsu(232))
    assert ringkas_disk_dari_state(state)["tingkat"] == "aman"


def test_modul_tidak_menarik_torch_cv2_atau_ultralytics():
    src = Path(__file__).resolve().parents[2] / "src"
    skrip = (
        "import sys\n"
        "for m in ('torch', 'cv2', 'ultralytics'):\n"
        "    sys.modules[m] = None\n"
        "import palmgrade.services.pemantau_disk\n"
    )
    hasil = subprocess.run(
        [sys.executable, "-c", skrip], capture_output=True, text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"}, timeout=60,
    )
    assert hasil.returncode == 0, hasil.stderr[-800:]
