"""Unit tests untuk LicenseLocalRepo — high-water mark jam di SQLite.

Repo ini tinggal satu angka: detik Unix tertinggi yang pernah dilihat mesin
ini. Kalau angka ini bisa turun, seluruh sistem langganan bisa dijebol cukup
dengan mengubah tanggal di BIOS. Test mengunci:
- init idempotent (row id=1 selalu ada, nilai awal 0).
- ratchet naik saat nilainya lebih besar.
- ratchet DIABAIKAN saat nilainya lebih kecil (monotonik).
- nilainya bertahan lintas instance (proses restart).

Pakai `asyncio.run` stdlib (repo async via aiosqlite), DB throwaway di tmp_path —
konsisten dengan test worker lain, CI tetap ringan.
"""
from __future__ import annotations

import asyncio

import pytest

from palmgrade.license.local_repo import LicenseLocalRepo


@pytest.fixture
def repo(tmp_path):
    r = LicenseLocalRepo(db_path=tmp_path / "license.db")
    asyncio.run(r.init())
    return r


def test_init_starts_at_zero(repo):
    assert asyncio.run(repo.read_max_seen()) == 0


def test_init_is_idempotent(tmp_path):
    r = LicenseLocalRepo(db_path=tmp_path / "license.db")
    asyncio.run(r.init())
    asyncio.run(r.init())  # tidak boleh error / tidak menggandakan row
    assert asyncio.run(r.read_max_seen()) == 0


def test_ratchet_moves_forward(repo):
    assert asyncio.run(repo.ratchet(1000)) == 1000
    assert asyncio.run(repo.read_max_seen()) == 1000


def test_ratchet_ignores_older_time(repo):
    asyncio.run(repo.ratchet(5000))
    # Jam dimundurkan → nilai lama yang menang, dan itulah yang dikembalikan.
    assert asyncio.run(repo.ratchet(3000)) == 5000
    assert asyncio.run(repo.read_max_seen()) == 5000


def test_value_survives_a_new_instance(tmp_path):
    db = tmp_path / "license.db"
    first = LicenseLocalRepo(db_path=db)
    asyncio.run(first.init())
    asyncio.run(first.ratchet(4242))

    second = LicenseLocalRepo(db_path=db)
    asyncio.run(second.init())
    assert asyncio.run(second.read_max_seen()) == 4242
