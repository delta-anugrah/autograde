"""`console_main.lifespan`'s own startup warnings — not `seed_default_accounts`
itself (see `test_akun_bawaan.py`), and not `ConsoleStore.has_support_account`
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

import pytest
from fastapi import FastAPI

from palmgrade import console_main
from palmgrade.core.config import _DEFAULT_WEBHOOK_SECRET, Settings
from palmgrade.domain.operator_auth import hash_password
from palmgrade.integrations.erp.outbox_store import ErpOutboxStore
from palmgrade.integrations.notifications.line_client import LineClient
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.routes import console_deps
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.erp_queue import ErpQueue

NO_SUPPORT_MESSAGE = "No account has the support role"


def _service(tmp_path, *, with_support: bool, **setelan) -> ConsoleService:
    # repo_root redirected here, not the real one: state_dir (and so
    # console_db_path/log_db_path) derives from it, and this must never touch a
    # developer's own state/console.db.
    settings = Settings(
        repo_root=tmp_path,
        console_default_hash="",
        console_support_hash="",
        erp_url="",
        **setelan,
    )
    store = ConsoleStore(settings.console_db_path)
    store.upsert_operator_manual(
        {
            "email": "operator@pks.test",
            "nama": "Operator",
            "password_hash": hash_password("sawit2026"),
        }
    )
    if with_support:
        store.set_role(
            store.operator_by_email("operator@pks.test")["id"], "support"
        )
    # With an ErpQueue, as get_console_service always builds it: the lifespan warms
    # get_dev_service, which reads the queue's outbox.
    erp_queue = ErpQueue(store, ErpOutboxStore(settings.erp_outbox_db_path))
    return ConsoleService(settings, store, LineClient(settings), erp_queue=erp_queue)


def _run_lifespan(service: ConsoleService, caplog, *, selama=lambda: None) -> None:
    """One pass through `lifespan`: enter, run `selama`, then leave.

    `get_console_service` is patched on `console_main`'s own module dict —
    that is the name `lifespan` actually calls, since `from .routes.console
    import get_console_service` bound it there at import time. It is patched
    on `console_deps` too: the singletons the lifespan warms (`get_auth_service`,
    `get_dev_service`) call it by that module's name. Their caches are emptied
    before and after, so no instance built on this `tmp_path` outlives the test.
    """
    original = console_main.get_console_service
    original_deps = console_deps.get_console_service
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    console_main.get_console_service = lambda: service
    console_deps.get_console_service = lambda: service
    _kosongkan_singleton()
    try:
        async def _runner() -> None:
            async with console_main.lifespan(FastAPI()):
                selama()

        with caplog.at_level(logging.WARNING):
            asyncio.run(_runner())
    finally:
        console_main.get_console_service = original
        console_deps.get_console_service = original_deps
        _kosongkan_singleton()
        # `lifespan` removes its logging on a clean exit, but not when startup
        # raises (the secret tests below): the SqliteLogHandler would stay on
        # the root logger, and every later test's WARNING/ERROR would log a
        # write attempt against this closed, temp-dir LogStore.
        root.handlers = original_handlers


def _kosongkan_singleton() -> None:
    console_deps.get_auth_service.cache_clear()
    console_deps.get_dev_service.cache_clear()
    console_deps.get_lapor_discord.cache_clear()


def test_layanan_sesi_dan_log_sudah_dibuat_sebelum_permintaan_pertama(tmp_path, caplog):
    """Batch 2.5: login, `/state`, dan tab Log jalan di thread pool, dan `lru_cache`
    tidak mencegah dua thread membuat instance pada panggilan pertama. Dua
    `AuthService` = dua kunci login, dan hitungan sandi salah bisa dilewati lagi.
    Jadi keduanya dibuat di lifespan, sebelum konsol melayani satu permintaan pun."""
    service = _service(tmp_path, with_support=True)
    terlihat = {}

    def selama() -> None:
        terlihat["auth"] = console_deps.get_auth_service.cache_info().currsize
        terlihat["dev"] = console_deps.get_dev_service.cache_info().currsize
        terlihat["store"] = console_deps.get_auth_service()._store

    _run_lifespan(service, caplog, selama=selama)

    assert terlihat == {"auth": 1, "dev": 1, "store": service.store}


def test_warning_fires_when_there_is_no_support_account(tmp_path, caplog):
    """The exact bug this branch fixes: every account `operator`, nobody able
    to reach the screen that would fix it."""
    service = _service(tmp_path, with_support=False)

    _run_lifespan(service, caplog)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(NO_SUPPORT_MESSAGE in r.message for r in warnings)


def test_warning_stays_quiet_when_a_support_account_exists(tmp_path, caplog):
    service = _service(tmp_path, with_support=True)

    _run_lifespan(service, caplog)

    assert not any(NO_SUPPORT_MESSAGE in r.message for r in caplog.records)


def test_konsol_produksi_dengan_secret_bawaan_menolak_start(tmp_path, caplog):
    service = _service(
        tmp_path, with_support=True, environment="production",
        webhook_secret=_DEFAULT_WEBHOOK_SECRET, internal_secret=_DEFAULT_WEBHOOK_SECRET,
    )
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
        _run_lifespan(service, caplog)


def test_konsol_produksi_dengan_secret_asli_menyala(tmp_path, caplog):
    service = _service(
        tmp_path, with_support=True, environment="production",
        webhook_secret="kunci-palsu-w", internal_secret="kunci-palsu-i",
    )
    _run_lifespan(service, caplog)  # tidak melempar
