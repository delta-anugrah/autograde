"""Akun operator dan sesi login konsol (Fase 4), bagian dari `ConsoleStore`.

Dipisah dari `console_repository.py` (batch 2, 2026-09-28) karena berkas itu lewat
1.000 baris. Mixin, bukan store sendiri: satu berkas `console.db`, satu koneksi, satu
lock, dan semua pemanggil (AuthService, OperatorAdmin, akun bawaan, MasterDataWorker,
`make operator`, test) memakai `ConsoleStore` sejak awal. Isi method tidak berubah.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

from ..domain.operator_auth import normalise_email, normalise_nama, operator_id_for
from ..domain.role import ROLE_SUPPORT, filter_erp_role, sanitize_role


class AkunStore:
    """Disediakan `ConsoleStore`: koneksi, lock, dan role yang boleh datang dari AutoERP."""

    _db: sqlite3.Connection
    _lock: threading.Lock
    _erp_allowed_roles: frozenset[str]

    def upsert_operator_manual(self, row: dict[str, Any]) -> str:
        """Write an account that lives only on this PC (`make operator`).

        Refuses to touch a row AutoERP owns: backoffice owns those passwords, and a
        change made here would be silently undone by the next pull — worse than being
        told no, because the operator would believe the new password works.
        """
        return self._upsert_operator(
            row, origin="lokal", overwrite_origin=("lokal",), always_end_session=True
        )

    def upsert_operator_erp(self, row: dict[str, Any]) -> str:
        """Apply one `AutoGrade Operator` document from the §4.A pull.

        Refuses to touch a local row. The support and built-in accounts exist so a mill
        with no internet can be opened at all; a pull that flattened them would take
        that away at exactly the moment it is needed.
        """
        return self._upsert_operator(row, origin="erp", overwrite_origin=("erp",))

    def _upsert_operator(
        self,
        row: dict[str, Any],
        *,
        origin: str,
        overwrite_origin: tuple[str, ...],
        always_end_session: bool = False,
    ) -> str:
        """Add or update one account, id derived from the email.

        Deriving the id means both sources land on the same row for one person instead
        of beside each other — the same adoption trick as trucks (§4.B). `active` is
        AutoERP's word for it and `status` is ours; the pull passes the former.
        """
        email = normalise_email(row["email"])
        operator_id = operator_id_for(email)
        status = row.get("status") or ("active" if row.get("active", 1) else "off")
        with self._lock, self._db:
            existing = self._db.execute(
                "SELECT origin, password_hash, status, role FROM operators WHERE id = ?",
                (operator_id,),
            ).fetchone()
            if existing and existing["origin"] not in overwrite_origin:
                return operator_id
            # Only an ERP row sets `role` here, via the allow-list. Otherwise keep
            # the existing role — overwriting it would erase a local account's role
            # every time `make operator` resets its password.
            if origin == "erp":
                role = filter_erp_role(row.get("role"), self._erp_allowed_roles)
            elif existing is not None:
                role = existing["role"]
            else:
                role = sanitize_role(row.get("role"))
            # Worked out before the write, while the old row is still readable.
            end_session = always_end_session or existing is None or any(
                existing[column] != new_value
                for column, new_value in (
                    ("password_hash", row["password_hash"]),
                    ("status", status),
                )
            )
            self._db.execute(
                """INSERT INTO operators
                       (id, email, full_name, password_hash, status, origin, erp_name, role, created_at)
                   VALUES (:id, :email, :full_name, :password_hash, :status, :origin, :erp_name, :role, :created_at)
                   ON CONFLICT(id) DO UPDATE SET
                       email          = excluded.email,
                       full_name      = excluded.full_name,
                       password_hash  = excluded.password_hash,
                       status         = excluded.status,
                       origin         = excluded.origin,
                       erp_name       = excluded.erp_name,
                       role           = excluded.role,
                       fail_count     = 0,
                       last_failed_at = NULL""",
                {
                    "id": operator_id,
                    "email": email,
                    "full_name": normalise_nama(row.get("full_name") or email),
                    "password_hash": row["password_hash"],
                    "status": status,
                    "origin": origin,
                    "role": role,
                    "erp_name": row.get("erp_name"),
                    "created_at": time.time(),
                },
            )
            # A new password, or an account switched off by a pull: every session opened
            # before it ends. A password is reset because someone saw it, and a session
            # that outlives the reset would make it a formality.
            #
            # But ONLY then. A pull re-reads unchanged rows by design (`_rewind` steps
            # back a few seconds because two clocks never agree), so deleting here
            # unconditionally signed the operator out on every sync — every 5 minutes at
            # the mill, with the screen blaming an expired session. Seen in a browser
            # 2026-09-15.
            if end_session:
                self._db.execute("DELETE FROM sesi WHERE operator_id = ?", (operator_id,))
        return operator_id

    def operator(self, operator_id: str) -> dict[str, Any] | None:
        """The whole row, hash included — for checking a password, and nothing else."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM operators WHERE id = ?", (operator_id,)
            ).fetchone()
        return dict(row) if row else None

    def operator_by_email(self, email: str) -> dict[str, Any] | None:
        """Sign-in has an email, not an id. Kept here rather than derived by the caller
        so the normalisation rule stays in one place."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM operators WHERE email = ?", (normalise_email(email),)
            ).fetchone()
        return dict(row) if row else None

    def operators(self) -> list[dict[str, Any]]:
        """What the sign-in screen may show before anyone is in: active accounts, no
        hashes. Whatever this returns is readable by any unauthenticated page."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, email, full_name, status, origin FROM operators "
                "WHERE status = 'active' ORDER BY full_name"
            ).fetchall()
        return [dict(row) for row in rows]

    def akun_untuk_support(self, *, now: float) -> list[dict[str, Any]]:
        """Every account on this PC — active or not — for the support Accounts screen.

        Columns are named one by one, never `SELECT *`: this list leaves the process
        as JSON, and neither the password hash nor a column added to `operators`
        later may ride along unseen. `sesi_aktif` counts sessions that still work
        (`expires_at > now`), not rows `purge_sessions` has not reached yet.
        Active accounts first, so the ones that can sign in are at the top.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT o.email, o.full_name, o.role, o.origin, o.status, o.created_at,
                          o.fail_count, o.last_failed_at,
                          (SELECT COUNT(*) FROM sesi s
                            WHERE s.operator_id = o.id AND s.expires_at > ?) AS sesi_aktif
                     FROM operators o
                    ORDER BY o.status = 'active' DESC, o.full_name COLLATE NOCASE, o.email""",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def has_support_account(self) -> bool:
        """Whether any active account can reach the developer screens.

        Existence check in SQL, not a Python loop over `operators()`: the
        lifespan asks this once at every startup, and a mill can carry years
        of accounts by then.
        """
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM operators WHERE role = ? AND status = 'active' LIMIT 1",
                (ROLE_SUPPORT,),
            ).fetchone()
        return row is not None

    def set_operator_status(self, operator_id: str, status: str) -> None:
        """`off` takes the account off the sign-in screen and ends the sessions it still
        holds — that is how a leaver or a shared password is handled.

        The sessions are deleted, not just filtered out by `session()`: filtering alone
        would hand an old, unexpired token its power back the moment the account is
        switched on again.
        """
        with self._lock, self._db:
            self._db.execute("UPDATE operators SET status = ? WHERE id = ?", (status, operator_id))
            if status != "active":
                self._db.execute("DELETE FROM sesi WHERE operator_id = ?", (operator_id,))

    def set_role(self, operator_id: str, role: str) -> None:
        """Set one account's role. An unknown value is stored as `operator`,
        not trusted from the caller — this column gates the piston screen."""
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET role = ? WHERE id = ?",
                (sanitize_role(role), operator_id),
            )

    def record_login_failure(self, operator_id: str, *, now: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET fail_count = fail_count + 1, last_failed_at = ? "
                "WHERE id = ?",
                (now, operator_id),
            )

    def clear_login_failures(self, operator_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE operators SET fail_count = 0, last_failed_at = NULL WHERE id = ?",
                (operator_id,),
            )

    def create_session(self, token: str, operator_id: str, *, now: float, ttl_s: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO sesi (token, operator_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token, operator_id, now, now + ttl_s),
            )

    def session(self, token: str, *, now: float) -> dict[str, Any] | None:
        """Who is behind a token — None when it is unknown, expired, or the operator
        has been switched off since."""
        with self._lock:
            row = self._db.execute(
                """SELECT s.operator_id, s.expires_at, o.full_name, o.email, o.origin, o.role
                     FROM sesi s JOIN operators o ON o.id = s.operator_id
                    WHERE s.token = ? AND s.expires_at > ? AND o.status = 'active'""",
                (token, now),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sesi WHERE token = ?", (token,))

    def purge_sessions(self, *, now: float) -> int:
        """Sweep what has expired; returns how many rows went."""
        with self._lock, self._db:
            cursor = self._db.execute("DELETE FROM sesi WHERE expires_at <= ?", (now,))
        return cursor.rowcount
