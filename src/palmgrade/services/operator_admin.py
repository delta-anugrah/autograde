"""Local operator accounts: from the PC's terminal and from the support Accounts tab.

Two callers share these rules. `scripts/console-operator.py`, behind `make operator`,
runs on the PC itself. Since 2026-09-26 the Accounts tab (`/api/console/dev/akun/*`)
runs them from the screen too, so support can add an operator without AnyDesk and a
terminal. That reversed the old "no web lane" rule (CLAUDE.md rule 19) on purpose: the
lane sits behind `require_support`, and every change is logged with the email of the
account that made it, so it shows on the Log tab.

The screen gets its own methods (`tambah`, `ganti_sandi`, `atur_status`, `atur_role`)
instead of reusing the terminal's. A terminal user typing an existing email means
"reset that password"; a form titled "new account" that quietly replaces someone
else's password would be a bad surprise. The screen also refuses to switch off or
demote the account doing it: one wrong click there could leave the PC with no support
account to undo it.

Only **local** accounts are managed here. AutoERP owns the rest, and the store refuses
to let this overwrite one: a password changed here would be undone by the next pull,
which is worse than a refusal because the operator would believe it took effect.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..domain.operator_auth import (
    check_password_format,
    hash_password,
    normalise_email,
    normalise_nama,
    operator_id_for,
)
from ..domain.operator_error import (
    AKUN_DIRI_SENDIRI,
    AKUN_EMAIL_TIDAK_SAH,
    AKUN_MILIK_ERP,
    AKUN_NAMA_KOSONG,
    AKUN_SANDI_BEDA,
    AKUN_SUDAH_ADA,
    AKUN_TIDAK_ADA,
    InvalidInput,
)
from ..domain.role import ROLE_OPERATOR, sanitize_role
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

# One @, something on both sides, no whitespace. Not RFC 5322: the address is only a
# sign-in name here and is never mailed, but "budi pks.test" must not become an
# account nobody can type again at the gate.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")


def _email_sah(email: str) -> str:
    email = normalise_email(email)
    if not _EMAIL.fullmatch(email):
        raise InvalidInput(AKUN_EMAIL_TIDAK_SAH, "email operator tidak valid")
    return email


def _nama_sah(full_name: str) -> str:
    full_name = normalise_nama(full_name)
    if not full_name:
        raise InvalidInput(AKUN_NAMA_KOSONG, "nama operator tidak boleh kosong")
    return full_name


def _sandi_sah(sandi: str, sandi_again: str) -> None:
    if sandi != sandi_again:
        raise InvalidInput(AKUN_SANDI_BEDA, "sandi kedua tidak sama dengan yang pertama")
    check_password_format(sandi)


def _milik_erp(email: str) -> InvalidInput:
    # Refused loudly: silently doing nothing would read as success.
    return InvalidInput(
        AKUN_MILIK_ERP, f"{email} milik AutoERP. Ubah di AutoERP, bukan di PC ini", email=email
    )


class OperatorAdmin:
    def __init__(self, store: ConsoleStore) -> None:
        self._store = store

    # ------------------------------------------------------------ terminal

    def add_or_reset(
        self, email: str, full_name: str, sandi: str, sandi_again: str, role: str = ROLE_OPERATOR
    ) -> tuple[str, str]:
        """Add a local account, or reset the password of the one holding that email.

        Returns `(operator_id, role)`, the role actually stored, which is only ever
        `role` on a brand-new account. `ConsoleStore.upsert_operator_manual` keeps an
        EXISTING account's role untouched by a password reset (a role set once must not
        be erased by the next reset), so the caller is told what really landed rather
        than what it asked for. Promoting an existing account is `set_role`.

        A reset ends every session opened with the old password, since a password is
        reset because someone saw it. Nothing is stored unless every check passes.
        """
        email = _email_sah(email)
        full_name = _nama_sah(full_name)
        _sandi_sah(sandi, sandi_again)

        owner = self._store.operator(operator_id_for(email))
        if owner is not None and owner["origin"] == "erp":
            raise _milik_erp(email)
        operator_id = self._store.upsert_operator_manual(
            {
                "email": email,
                "full_name": full_name,
                "password_hash": hash_password(sandi),
                "role": sanitize_role(role),
            }
        )
        # Read back rather than assumed: the row is the only source of truth for
        # which role actually landed (new account vs. an existing one kept its own).
        return operator_id, self._store.operator(operator_id)["role"]

    def set_role(self, email: str, role: str) -> str:
        """Change one EXISTING local account's role. Returns the role actually stored.

        `add_or_reset` never touches the role of an account that already exists, on
        purpose, so a password reset can never double as a silent promotion. This is
        the explicit, separate action for changing a role on its own.
        """
        operator_id = operator_id_for(email)
        if self._store.operator(operator_id) is None:
            # A typo must not read as success while the real account stays live.
            raise InvalidInput(AKUN_TIDAK_ADA, f"operator {normalise_email(email)!r} tidak ada")
        sanitized = sanitize_role(role)
        self._store.set_role(operator_id, sanitized)
        return sanitized

    def switch_off(self, email: str) -> None:
        """Take an account off the sign-in screen and end its sessions now.

        Works on AutoERP accounts too, on purpose: someone standing at the mill needs to
        be able to shut out a leaver before the next pull. The pull puts it back if
        AutoERP still says the account is active, which is the correct owner winning.
        """
        operator_id = operator_id_for(email)
        if self._store.operator(operator_id) is None:
            # A typo must not read as success while the real account stays live.
            raise InvalidInput(AKUN_TIDAK_ADA, f"operator {normalise_email(email)!r} tidak ada")
        self._store.set_operator_status(operator_id, "off")

    def listing(self) -> list[dict[str, Any]]:
        return self._store.operators()

    # ------------------------------------------------------ Accounts tab

    def tambah(
        self, email: str, full_name: str, sandi: str, sandi_again: str, role: str, *, oleh: str
    ) -> dict[str, str]:
        """Create a NEW local account. An email that already exists is refused.

        Returns the email and the role actually stored. An unknown role lands on
        `operator` (`sanitize_role`): the role decides who can open the Danger Zone.
        """
        email = _email_sah(email)
        full_name = _nama_sah(full_name)
        _sandi_sah(sandi, sandi_again)
        ada = self._store.operator(operator_id_for(email))
        if ada is not None:
            if ada["origin"] != "lokal":
                raise _milik_erp(email)
            raise InvalidInput(AKUN_SUDAH_ADA, f"{email} sudah ada", email=email)
        operator_id = self._store.upsert_operator_manual(
            {
                "email": email,
                "full_name": full_name,
                "password_hash": hash_password(sandi),
                "role": sanitize_role(role),
            }
        )
        role = self._store.operator(operator_id)["role"]
        logger.warning(
            "Akun lokal %s dibuat oleh %s, role %s", email, normalise_email(oleh), role
        )
        return {"email": email, "role": role}

    def ganti_sandi(self, email: str, sandi: str, sandi_again: str, *, oleh: str) -> None:
        """New password for a local account. Every session it holds ends now.

        Name, role and status stay as they are. The terminal's reset also switches an
        account back on; on the screen that is its own button, so a password change
        must not quietly let a switched-off account back in.
        """
        row = self._akun_lokal(email)
        _sandi_sah(sandi, sandi_again)
        self._store.upsert_operator_manual(
            {
                "email": row["email"],
                "full_name": row["full_name"],
                "password_hash": hash_password(sandi),
                "status": row["status"],
            }
        )
        logger.warning(
            "Sandi akun lokal %s diganti oleh %s", row["email"], normalise_email(oleh)
        )

    def atur_status(self, email: str, aktif: bool, *, oleh: str) -> str:
        """Switch a local account off (its sessions end now) or back on."""
        row = self._akun_lokal(email)
        self._bukan_diri_sendiri(row["email"], oleh)
        status = "active" if aktif else "off"
        self._store.set_operator_status(row["id"], status)
        logger.warning(
            "Akun lokal %s %s oleh %s",
            row["email"],
            "diaktifkan" if aktif else "dimatikan",
            normalise_email(oleh),
        )
        return status

    def atur_role(self, email: str, role: str, *, oleh: str) -> str:
        """Change a local account's role. Returns the role actually stored.

        No session is ended: `ConsoleStore.session` reads the role from the account
        on every request, so the change applies from the next click.
        """
        row = self._akun_lokal(email)
        self._bukan_diri_sendiri(row["email"], oleh)
        role = sanitize_role(role)
        self._store.set_role(row["id"], role)
        logger.warning(
            "Role akun lokal %s diubah jadi %s oleh %s", row["email"], role, normalise_email(oleh)
        )
        return role

    def _akun_lokal(self, email: str) -> dict[str, Any]:
        """The local account holding this email, or a coded refusal."""
        email = normalise_email(email)
        row = self._store.operator(operator_id_for(email))
        if row is None:
            raise InvalidInput(AKUN_TIDAK_ADA, f"operator {email!r} tidak ada", email=email)
        # An allow-list, not `== "erp"`: an origin added later is not ours to edit.
        if row["origin"] != "lokal":
            raise _milik_erp(email)
        return row

    @staticmethod
    def _bukan_diri_sendiri(email: str, oleh: str) -> None:
        if normalise_email(email) == normalise_email(oleh):
            raise InvalidInput(
                AKUN_DIRI_SENDIRI, "akun sendiri tidak bisa dimatikan atau diubah role-nya"
            )
