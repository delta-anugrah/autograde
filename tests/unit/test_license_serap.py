"""`LicenseLocalRepo.serap`: penanda jam dari license.db lama ikut pindah, yang tertinggi menang."""
from __future__ import annotations

import asyncio

from palmgrade.license.local_repo import LicenseLocalRepo


def _repo(path, nilai: int) -> LicenseLocalRepo:
    repo = LicenseLocalRepo(path)
    asyncio.run(repo.init())
    asyncio.run(repo.ratchet(nilai))
    return repo


def test_penanda_jam_lama_ikut(tmp_path):
    _repo(tmp_path / "lama.db", 2_000_000_000)
    baru = LicenseLocalRepo(tmp_path / "state" / "license.db")
    (tmp_path / "state").mkdir()

    assert asyncio.run(baru.serap(tmp_path / "lama.db")) == 2_000_000_000


def test_penanda_tidak_pernah_turun(tmp_path):
    """Memundurkan penanda sama dengan mengizinkan jam PC dimundurkan."""
    _repo(tmp_path / "lama.db", 100)
    baru = _repo(tmp_path / "baru.db", 500)

    assert asyncio.run(baru.serap(tmp_path / "lama.db")) == 500


def test_init_membuat_folder_yang_belum_ada(tmp_path):
    """Jalur native memberi tiap line `state/line-N` yang belum tentu sudah ada;
    lisensi yang gagal membuka berkasnya = line menolak start."""
    repo = LicenseLocalRepo(tmp_path / "state" / "line-1" / "license.db")

    asyncio.run(repo.init())

    assert asyncio.run(repo.read_max_seen()) == 0
