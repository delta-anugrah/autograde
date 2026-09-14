"""Signing in at the console (Fase 4, plan §6.5).

The service behind the keypad: what a wrong PIN costs, what a shut keypad answers, and
what a session is worth once the operator holding it is switched off. The routes and the
screen are thin over this, so this is where the rules are pinned.
"""

from __future__ import annotations

import pytest

from palmgrade.domain.operator_auth import hash_pin, operator_id_for
from palmgrade.domain.operator_error import PIN_SALAH, TERKUNCI, OperatorError
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.auth_service import AuthService

NAMA = "Pak Budi"
PIN = "142536"
WRONG = "998877"


def _auth(tmp_path, *, now: float = 1000.0):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator({"nama": NAMA, "pin_hash": hash_pin(PIN)})
    clock = [now]
    return AuthService(store, now=lambda: clock[0]), store, clock


def _fail(auth, times: int, clock) -> None:
    for _ in range(times):
        with pytest.raises(OperatorError):
            auth.login(operator_id_for(NAMA), WRONG)
        clock[0] += 1


def test_the_right_pin_opens_a_session_that_names_its_operator(tmp_path):
    auth, _, _ = _auth(tmp_path)

    token, operator = auth.login(operator_id_for(NAMA), PIN)

    assert operator["nama"] == NAMA
    assert auth.current(token)["nama"] == NAMA


def test_a_wrong_pin_says_nothing_about_which_part_was_wrong(tmp_path):
    """One answer for a wrong PIN, an unknown operator and a switched-off one: a shared
    screen must not let anyone map out who exists."""
    auth, _, _ = _auth(tmp_path)

    with pytest.raises(OperatorError) as wrong:
        auth.login(operator_id_for(NAMA), WRONG)
    with pytest.raises(OperatorError) as unknown:
        auth.login(operator_id_for("Tidak Ada"), PIN)

    assert wrong.value.code == unknown.value.code == PIN_SALAH


def test_a_pin_of_the_wrong_shape_never_reaches_the_hash(tmp_path, monkeypatch):
    """scrypt is deliberately slow. A request body with a megabyte "PIN" must be turned
    away before it gets there — and still count as a wrong try."""
    auth, store, _ = _auth(tmp_path)
    hashed = []
    monkeypatch.setattr(
        "palmgrade.services.auth_service.verify_pin", lambda *args: hashed.append(args) or False
    )

    with pytest.raises(OperatorError) as refused:
        auth.login(operator_id_for(NAMA), "9" * 100_000)

    assert refused.value.code == PIN_SALAH
    assert hashed == []
    assert store.operator(operator_id_for(NAMA))["gagal_count"] == 1


def test_five_wrong_pins_shut_the_keypad_and_the_answer_says_for_how_long(tmp_path):
    auth, _, clock = _auth(tmp_path)

    _fail(auth, 5, clock)

    with pytest.raises(OperatorError) as locked:
        auth.login(operator_id_for(NAMA), PIN)
    assert locked.value.code == TERKUNCI
    assert locked.value.params["detik"] > 0


def test_the_right_pin_gets_in_once_the_lockout_has_run_out(tmp_path):
    """And the count goes back to zero, so a bad-glove evening does not follow the
    operator into the next shift."""
    auth, store, clock = _auth(tmp_path)
    _fail(auth, 5, clock)

    clock[0] += 120
    token, _ = auth.login(operator_id_for(NAMA), PIN)

    assert auth.current(token) is not None
    assert store.operator(operator_id_for(NAMA))["gagal_count"] == 0


def test_a_session_lasts_a_shift_and_not_a_day(tmp_path):
    auth, _, clock = _auth(tmp_path)
    token, _ = auth.login(operator_id_for(NAMA), PIN)

    clock[0] += 12 * 60 * 60 - 60
    assert auth.current(token) is not None

    clock[0] += 120
    assert auth.current(token) is None


def test_signing_out_ends_the_session_at_once(tmp_path):
    auth, _, _ = _auth(tmp_path)
    token, _ = auth.login(operator_id_for(NAMA), PIN)

    auth.logout(token)

    assert auth.current(token) is None


def test_no_cookie_and_a_made_up_cookie_are_both_nobody(tmp_path):
    auth, _, _ = _auth(tmp_path)

    assert auth.current(None) is None
    assert auth.current("tidak-pernah-ada") is None


def test_switching_an_operator_off_ends_the_session_they_still_hold(tmp_path):
    """How a leaver, or a PIN the whole shift has seen, is handled: one flag, and the
    screen in their hand stops writing."""
    auth, store, _ = _auth(tmp_path)
    token, _ = auth.login(operator_id_for(NAMA), PIN)

    store.set_operator_status(operator_id_for(NAMA), "off")

    assert auth.current(token) is None


def test_the_keypad_gets_names_only(tmp_path):
    """This listing is read before anyone is signed in."""
    auth, _, _ = _auth(tmp_path)

    [operator] = auth.operators()

    assert set(operator) == {"id", "nama", "status"}
