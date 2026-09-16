"""Signing an operator in at the console (Fase 4, plan §6.5).

Thin over `domain/operator_auth.py` and the store: the rules live in the domain, the
rows in the store, and this decides the order — check the lockout before the password,
give every refusal the same words, and clear the counter only on the way in.

Nothing here reaches AutoERP. The hash was pulled earlier (§4.A) or written locally, so
a sign-in works with the line offline, which is the point of the whole design.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..domain.operator_auth import (
    SESSION_TTL_S,
    lockout_seconds_left,
    new_session_token,
    verify_password,
)
from ..domain.operator_error import SANDI_SALAH, TERKUNCI, InvalidInput, OperatorError
from ..repositories.console_repository import ConsoleStore

# One answer for a wrong password, an account that does not exist, and one switched off:
# a screen the whole shift can see must not let anyone map out who has an account.
_REFUSED = "email atau sandi salah"

# Hashing is slow on purpose, so an oversized body is turned away before it gets there —
# and still counts as a wrong try. Well past any real password.
_MAX_PASSWORD_BYTES = 1024


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
        """Accounts for the sign-in screen — read before anyone is in, so nothing more.

        They fill the email field on a touchscreen where typing one is slow; the password
        is still required, so this is a convenience, not a way in.
        """
        return self._store.operators()

    def login(self, email: str, password: str) -> tuple[str, dict[str, Any]]:
        """Session token and operator, or an `OperatorError` the screen words itself.

        The lockout is checked before the password on purpose: guessing must not stay
        cheap just because the account exists, and an operator who is locked out needs
        to be told to wait rather than told their password is wrong.
        """
        now = self._now()
        row = self._store.operator_by_email(email)
        if row is None or row["status"] != "active":
            raise InvalidInput(SANDI_SALAH, _REFUSED)

        operator_id = row["id"]
        locked = lockout_seconds_left(
            row["fail_count"], last_failed_at=row["last_failed_at"], now=now
        )
        if locked:
            raise OperatorError(TERKUNCI, f"login terkunci {locked} detik lagi", detik=locked)

        if not self._password_plausible(password) or not verify_password(
            password, row["password_hash"]
        ):
            self._store.record_login_failure(operator_id, now=now)
            raise InvalidInput(SANDI_SALAH, _REFUSED)

        self._store.clear_login_failures(operator_id)
        token = new_session_token()
        self._store.create_session(token, operator_id, now=now, ttl_s=self._ttl_s)
        # One sweep per sign-in, and nowhere else: enough to keep the table from growing
        # for the life of a factory PC, without a worker of its own.
        self._store.purge_sessions(now=now)
        return token, {"id": operator_id, "email": row["email"], "full_name": row["full_name"]}

    @staticmethod
    def _password_plausible(password: object) -> bool:
        return (
            isinstance(password, str)
            and bool(password)
            and len(password.encode("utf-8", "ignore")) <= _MAX_PASSWORD_BYTES
        )

    def current(self, token: str | None) -> dict[str, Any] | None:
        """Who is holding this cookie, or None — unknown, expired, or switched off."""
        if not token:
            return None
        return self._store.session(token, now=self._now())

    def logout(self, token: str | None) -> None:
        if token:
            self._store.delete_session(token)
