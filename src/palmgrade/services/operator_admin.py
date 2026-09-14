"""Operator accounts, managed from the PC itself (Fase 4, plan §6.5).

Deliberately not a web lane: an account the console page can create is an account
anybody on the mill LAN can create. `scripts/console-operator.py`, behind
`make operator`, is the only caller.
"""

from __future__ import annotations

from typing import Any

from ..domain.operator_auth import check_pin_format, hash_pin, normalise_nama, operator_id_for
from ..repositories.console_repository import ConsoleStore


class OperatorAdmin:
    def __init__(self, store: ConsoleStore) -> None:
        self._store = store

    def add_or_reset(self, nama: str, pin: str, pin_again: str) -> str:
        """Add an operator, or reset the PIN of the one already holding that name.

        A reset ends every session opened with the old PIN — a PIN is reset because
        someone saw it. Nothing is stored unless every check passes.
        """
        nama = normalise_nama(nama)
        if not nama:
            raise ValueError("nama operator tidak boleh kosong")
        if pin != pin_again:
            raise ValueError("PIN kedua tidak sama dengan yang pertama")
        check_pin_format(pin)
        return self._store.upsert_operator({"nama": nama, "pin_hash": hash_pin(pin)})

    def switch_off(self, nama: str) -> None:
        """Take an operator off the keypad and end their sessions now."""
        operator_id = operator_id_for(nama)
        if self._store.operator(operator_id) is None:
            # A typo must not read as success while the real account stays live.
            raise ValueError(f"operator {normalise_nama(nama)!r} tidak ada")
        self._store.set_operator_status(operator_id, "off")

    def listing(self) -> list[dict[str, Any]]:
        return self._store.operators()
