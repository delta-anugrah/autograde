"""Local operator accounts, managed from the PC itself (Fase 4, plan §6.5).

Deliberately not a web lane: an account the console page can create is an account
anybody on the mill LAN can create. `scripts/console-operator.py`, behind
`make operator`, is the only caller.

Only **local** accounts are managed here. AutoERP owns the rest, and the store refuses
to let this overwrite one — a password changed here would be undone by the next pull,
which is worse than a refusal because the operator would believe it took effect.
"""

from __future__ import annotations

from typing import Any

from ..domain.operator_auth import (
    check_password_format,
    hash_password,
    normalise_email,
    normalise_nama,
    operator_id_for,
)
from ..domain.peran import PERAN_OPERATOR, peran_sah
from ..repositories.console_repository import ConsoleStore


class OperatorAdmin:
    def __init__(self, store: ConsoleStore) -> None:
        self._store = store

    def add_or_reset(
        self, email: str, nama: str, sandi: str, sandi_again: str, peran: str = PERAN_OPERATOR
    ) -> tuple[str, str]:
        """Add a local account, or reset the password of the one holding that email.

        Returns `(operator_id, peran)` — the role actually stored, which is only ever
        `peran` on a brand-new account. `ConsoleStore.upsert_operator_lokal` keeps an
        EXISTING account's role untouched by a password reset — a role set once must not
        be erased by the next reset — so the caller is told what really landed rather
        than what it asked for. Promoting an existing account is `set_peran`.

        A reset ends every session opened with the old password — a password is reset
        because someone saw it. Nothing is stored unless every check passes.
        """
        email = normalise_email(email)
        if not email or "@" not in email:
            raise ValueError("email operator tidak valid")
        nama = normalise_nama(nama)
        if not nama:
            raise ValueError("nama operator tidak boleh kosong")
        if sandi != sandi_again:
            raise ValueError("sandi kedua tidak sama dengan yang pertama")
        check_password_format(sandi)

        owner = self._store.operator(operator_id_for(email))
        if owner is not None and owner["asal"] == "erp":
            # Refused loudly: silently doing nothing would read as success.
            raise ValueError(
                f"{email} milik AutoERP — ubah sandinya di AutoERP, bukan di PC ini"
            )
        operator_id = self._store.upsert_operator_lokal(
            {
                "email": email,
                "nama": nama,
                "password_hash": hash_password(sandi),
                "peran": peran_sah(peran),
            }
        )
        # Read back rather than assumed: the row is the only source of truth for
        # which role actually landed (new account vs. an existing one kept its own).
        return operator_id, self._store.operator(operator_id)["peran"]

    def set_peran(self, email: str, peran: str) -> str:
        """Change one EXISTING local account's role. Returns the role actually stored.

        `add_or_reset` never touches the role of an account that already exists — on
        purpose, so a password reset can never double as a silent promotion. This is
        the explicit, separate action for changing a role on its own.
        """
        operator_id = operator_id_for(email)
        if self._store.operator(operator_id) is None:
            # A typo must not read as success while the real account stays live.
            raise ValueError(f"operator {normalise_email(email)!r} tidak ada")
        disahkan = peran_sah(peran)
        self._store.set_peran(operator_id, disahkan)
        return disahkan

    def switch_off(self, email: str) -> None:
        """Take an account off the sign-in screen and end its sessions now.

        Works on AutoERP accounts too, on purpose: someone standing at the mill needs to
        be able to shut out a leaver before the next pull. The pull puts it back if
        AutoERP still says the account is active, which is the correct owner winning.
        """
        operator_id = operator_id_for(email)
        if self._store.operator(operator_id) is None:
            # A typo must not read as success while the real account stays live.
            raise ValueError(f"operator {normalise_email(email)!r} tidak ada")
        self._store.set_operator_status(operator_id, "off")

    def listing(self) -> list[dict[str, Any]]:
        return self._store.operators()
