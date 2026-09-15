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
from ..repositories.console_repository import ConsoleStore


class OperatorAdmin:
    def __init__(self, store: ConsoleStore) -> None:
        self._store = store

    def add_or_reset(self, email: str, nama: str, sandi: str, sandi_again: str) -> str:
        """Add a local account, or reset the password of the one holding that email.

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
        return self._store.upsert_operator_lokal(
            {"email": email, "nama": nama, "password_hash": hash_password(sandi)}
        )

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
