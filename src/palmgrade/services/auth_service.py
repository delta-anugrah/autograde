"""Signing an operator in at the console (Fase 4, plan §6.5).

Thin over `domain/operator_auth.py` and the store: the rules live in the domain, the
rows in the store, and this decides the order — check the lockout before the PIN, give
every refusal the same words, and clear the counter only on the way in.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..domain.operator_auth import (
    SESSION_TTL_S,
    lockout_seconds_left,
    new_session_token,
    verify_pin,
)
from ..domain.operator_error import PIN_SALAH, TERKUNCI, InvalidInput, OperatorError
from ..repositories.console_repository import ConsoleStore

# One answer for a wrong PIN, an operator who does not exist, and one switched off: a
# screen the whole shift can see must not let anyone map out who has an account.
_REFUSED = "operator tidak dikenal atau PIN salah"


class AuthService:
    def __init__(
        self,
        store: ConsoleStore,
        *,
        ttl_s: int = SESSION_TTL_S,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._ttl_s = ttl_s
        self._now = now

    def operators(self) -> list[dict[str, Any]]:
        """Names for the keypad — read before anyone is signed in, so nothing more."""
        return self._store.operators()

    def login(self, operator_id: str, pin: str) -> tuple[str, dict[str, Any]]:
        """Session token and operator, or an `OperatorError` the screen words itself.

        The lockout is checked before the PIN on purpose: guessing must not stay cheap
        just because the account exists, and an operator who is locked out needs to be
        told to wait rather than told their PIN is wrong.
        """
        now = self._now()
        row = self._store.operator(operator_id)
        if row is None or row["status"] != "active":
            raise InvalidInput(PIN_SALAH, _REFUSED)

        locked = lockout_seconds_left(
            row["gagal_count"], last_failed_at=row["gagal_terakhir"], now=now
        )
        if locked:
            raise OperatorError(TERKUNCI, f"keypad terkunci {locked} detik lagi", detik=locked)

        if not verify_pin(pin, row["pin_hash"]):
            self._store.record_login_failure(operator_id, now=now)
            raise InvalidInput(PIN_SALAH, _REFUSED)

        self._store.clear_login_failures(operator_id)
        token = new_session_token()
        self._store.create_session(token, operator_id, now=now, ttl_s=self._ttl_s)
        # One sweep per sign-in, and nowhere else: enough to keep the table from growing
        # for the life of a factory PC, without a worker of its own.
        self._store.purge_sessions(now=now)
        return token, {"id": operator_id, "nama": row["nama"]}

    def current(self, token: str | None) -> dict[str, Any] | None:
        """Who is holding this cookie, or None — unknown, expired, or switched off."""
        if not token:
            return None
        return self._store.session(token, now=self._now())

    def logout(self, token: str | None) -> None:
        if token:
            self._store.delete_session(token)
