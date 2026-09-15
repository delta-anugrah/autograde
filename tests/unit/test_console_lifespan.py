"""`console_main.lifespan`'s own startup warnings — not `seed_akun_bawaan`
itself (see `test_akun_bawaan.py`), and not `ConsoleStore.ada_akun_support`
(see `test_console_store.py`), but the log line the lifespan emits from them.

Driven with a real `ConsoleStore` on `tmp_path` and a `ConsoleService` built by
hand, `get_console_service` monkeypatched onto `console_main`'s own imported
name — never `create_console_app()`, which would reach for a developer's real
`state/console.db` (same reasoning as `test_dev_lane_peran.py`).

No `pytest-asyncio`: `lifespan` is driven with `asyncio.run`, like
`test_event_broadcast_worker.py` already does, so CI needs nothing beyond
`ruff pytest`.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI

from palmgrade import console_main
from palmgrade.core.config import Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.console_service import ConsoleService

PESAN_TANPA_SUPPORT = "Tidak ada akun dengan peran support"


def _service(tmp_path, *, dengan_support: bool) -> ConsoleService:
    # repo_root redirected here, not the real one: state_dir (and so
    # console_db_path/log_db_path) derives from it, and this must never touch a
    # developer's own state/console.db.
    settings = Settings(
        repo_root=tmp_path,
        console_default_hash="",
        console_support_hash="",
        erp_url="",
    )
    store = ConsoleStore(settings.console_db_path)
    store.upsert_operator_lokal(
        {
            "email": "operator@pks.test",
            "nama": "Operator",
            "password_hash": hash_password("sawit2026"),
        }
    )
    if dengan_support:
        store.set_peran(
            store.operator_by_email("operator@pks.test")["id"], "support"
        )
    return ConsoleService(settings, store, LineClient(settings))


def _jalankan_lifespan(service: ConsoleService, caplog) -> None:
    """One pass through `lifespan`: enter, then leave immediately.

    `get_console_service` is patched on `console_main`'s own module dict —
    that is the name `lifespan` actually calls, since `from .routes.console
    import get_console_service` bound it there at import time.
    """
    asli = console_main.get_console_service
    root = logging.getLogger()
    handlers_semula = list(root.handlers)
    console_main.get_console_service = lambda: service
    try:
        async def _runner() -> None:
            async with console_main.lifespan(FastAPI()):
                pass

        with caplog.at_level(logging.WARNING):
            asyncio.run(_runner())
    finally:
        console_main.get_console_service = asli
        # `lifespan` adds a SqliteLogHandler to the root logger and never
        # removes it (a real process keeps it for the app's whole life) — a
        # test run has to, or every later test's WARNING/ERROR logs a write
        # attempt against this closed, temp-dir LogStore.
        root.handlers = handlers_semula


def test_peringatan_menyala_kalau_tidak_ada_akun_support(tmp_path, caplog):
    """The exact bug this branch fixes: every account `operator`, nobody able
    to reach the screen that would fix it."""
    service = _service(tmp_path, dengan_support=False)

    _jalankan_lifespan(service, caplog)

    peringatan = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(PESAN_TANPA_SUPPORT in r.message for r in peringatan)


def test_peringatan_diam_kalau_ada_akun_support(tmp_path, caplog):
    service = _service(tmp_path, dengan_support=True)

    _jalankan_lifespan(service, caplog)

    assert not any(PESAN_TANPA_SUPPORT in r.message for r in caplog.records)
