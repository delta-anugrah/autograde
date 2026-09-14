"""Managing operator accounts from the PC, not from the screen (Fase 4, plan §6.5).

There is deliberately no web lane for this: an account that can be created from the
console page is one anybody on the mill LAN can create. The command runs on the PC
itself — `make operator` — and this is the logic behind it.
"""

from __future__ import annotations

import pytest

from palmgrade.domain.operator_auth import new_session_token, operator_id_for, verify_pin
from palmgrade.domain.operator_error import InvalidInput
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.operator_admin import OperatorAdmin

NAMA = "Pak Budi"
PIN = "142536"


def _admin(tmp_path) -> tuple[OperatorAdmin, ConsoleStore]:
    store = ConsoleStore(tmp_path / "console.db")
    return OperatorAdmin(store), store


def test_an_operator_added_can_sign_in_with_that_pin(tmp_path):
    admin, store = _admin(tmp_path)

    admin.add_or_reset(NAMA, PIN, PIN)

    row = store.operator(operator_id_for(NAMA))
    assert row["status"] == "active"
    assert verify_pin(PIN, row["pin_hash"])


def test_the_pin_has_to_be_typed_the_same_twice(tmp_path):
    """Typed blind on a terminal; one slip would lock the operator out on day one."""
    admin, store = _admin(tmp_path)

    with pytest.raises(ValueError, match="tidak sama"):
        admin.add_or_reset(NAMA, PIN, "142537")

    assert store.operator(operator_id_for(NAMA)) is None


def test_an_unusable_pin_is_refused_before_anything_is_stored(tmp_path):
    admin, store = _admin(tmp_path)

    with pytest.raises(InvalidInput):
        admin.add_or_reset(NAMA, "123456", "123456")

    assert store.operator(operator_id_for(NAMA)) is None


def test_an_operator_needs_a_name_the_keypad_can_show(tmp_path):
    admin, _ = _admin(tmp_path)

    with pytest.raises(ValueError, match="nama"):
        admin.add_or_reset("   ", PIN, PIN)


def test_adding_again_resets_the_pin_and_ends_the_old_sessions(tmp_path):
    """The forgotten-PIN path, and the seen-PIN path: same command."""
    admin, store = _admin(tmp_path)
    admin.add_or_reset(NAMA, PIN, PIN)
    token = new_session_token()
    store.create_session(token, operator_id_for(NAMA), now=1000.0, ttl_s=43200)

    admin.add_or_reset(NAMA, "908171", "908171")

    row = store.operator(operator_id_for(NAMA))
    assert verify_pin("908171", row["pin_hash"])
    assert not verify_pin(PIN, row["pin_hash"])
    assert store.session(token, now=1000.0) is None


def test_switching_an_operator_off_takes_them_off_the_keypad(tmp_path):
    admin, store = _admin(tmp_path)
    admin.add_or_reset(NAMA, PIN, PIN)

    admin.switch_off(" pak  budi ")

    assert admin.listing() == []
    assert store.operator(operator_id_for(NAMA))["status"] == "off"


def test_switching_off_a_name_nobody_has_says_so(tmp_path):
    """A typo must not look like success while the real account stays live."""
    admin, _ = _admin(tmp_path)

    with pytest.raises(ValueError, match="tidak ada"):
        admin.switch_off("Pak Bud")
