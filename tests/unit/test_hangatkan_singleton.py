"""`hangatkan_singleton()` membangun SEMUA singleton `lru_cache` konsol sebelum melayani.

Parkiran Task 7 batch 2.5: cuma dua yang dihangatkan. `lru_cache` tidak mencegah dua
thread pool membangun dua instance kalau panggilan pertamanya datang bersamaan; tiap
getter yang ditambah kelak harus ikut, dan test ini yang menagihnya.
"""
from __future__ import annotations

from palmgrade.routes import console_deps


def _getter_bercache() -> list[str]:
    return sorted(
        nama for nama, obj in vars(console_deps).items()
        if nama.startswith("get_") and callable(obj) and hasattr(obj, "cache_info")
    )


def test_semua_getter_bercache_dihangatkan(monkeypatch):
    semua = _getter_bercache()
    dipanggil: list[str] = []
    for nama in semua:
        monkeypatch.setattr(console_deps, nama, lambda nama=nama: dipanggil.append(nama))

    console_deps.hangatkan_singleton()

    assert len(semua) >= 9
    assert sorted(dipanggil) == semua
