"""Unit tests untuk LicenseLocalRepo — cache token + hash-chain di SQLite.

Repo ini menyimpan token JWS terakhir + rantai hash (anti-tamper) + high-water-mark
`max_seen_server_time` (dipakai manager buat deteksi rollback). Test mengunci:
- init idempotent (row id=1 selalu ada).
- write→read round-trip.
- hash-chain: prev bergeser mengikuti curr sebelumnya, curr deterministik.
- `max_seen_server_time` monotonik (MAX, tidak pernah turun).

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


def test_init_creates_default_row(repo):
    state = asyncio.run(repo.read())
    assert state.token_jws is None
    assert state.max_seen_server_time == 0
    assert state.hash_chain_curr is None


def test_init_is_idempotent(tmp_path):
    r = LicenseLocalRepo(db_path=tmp_path / "license.db")
    asyncio.run(r.init())
    asyncio.run(r.init())  # tidak boleh error / tidak menggandakan row
    state = asyncio.run(r.read())
    assert state.max_seen_server_time == 0


def test_write_then_read_roundtrip(repo):
    asyncio.run(repo.write_token("tok-1", server_time=1000))
    state = asyncio.run(repo.read())
    assert state.token_jws == "tok-1"
    assert state.max_seen_server_time == 1000
    assert state.last_sync_at is not None
    assert state.hash_chain_curr is not None
    assert state.hash_chain_prev is None  # write pertama: prev masih kosong


def test_hash_chain_advances(repo):
    asyncio.run(repo.write_token("tok-1", server_time=1000))
    first = asyncio.run(repo.read())

    asyncio.run(repo.write_token("tok-2", server_time=2000))
    second = asyncio.run(repo.read())

    # prev write kedua = curr write pertama (rantai bergerak).
    assert second.hash_chain_prev == first.hash_chain_curr
    assert second.hash_chain_curr != first.hash_chain_curr


def test_next_hash_is_deterministic(repo):
    a = repo._next_hash("prev", "token", 123)
    b = repo._next_hash("prev", "token", 123)
    c = repo._next_hash("prev", "token", 124)
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hexdigest


def test_max_seen_server_time_is_monotonic(repo):
    asyncio.run(repo.write_token("tok-1", server_time=5000))
    asyncio.run(repo.write_token("tok-2", server_time=3000))  # lebih kecil → diabaikan
    state = asyncio.run(repo.read())
    assert state.max_seen_server_time == 5000
    # token tetap ter-update meski server_time tidak naik.
    assert state.token_jws == "tok-2"
