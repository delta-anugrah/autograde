"""Signing in at the console (Fase 4, plan §6.5).

The service behind the sign-in screen: what a wrong password costs, what a shut screen
answers, and what a session is worth once the operator holding it is switched off. The
routes and the screen are thin over this, so this is where the rules are pinned.

Nothing here reaches AutoERP — the hash was pulled earlier or written locally. The test
that proves an ERP account signs in with the ERP switched off is the E2E one; what is
pinned here is that the service never asks anybody anything.
"""

from __future__ import annotations

import pytest

from palmgrade.domain.operator_auth import hash_password, operator_id_for
from palmgrade.domain.operator_error import SANDI_SALAH, TERKUNCI, OperatorError
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.auth_service import AuthService

EMAIL = "budi@pks.test"
NAMA = "Pak Budi"
SANDI = "sawit2026"
WRONG = "sawit2027"
# Written by AutoERP's passlib context, for the password in `SANDI`.
ERP_HASH = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"


def _auth(tmp_path, *, now: float = 1000.0):
    store = ConsoleStore(tmp_path / "console.db")
    store.upsert_operator_lokal(
        {"email": EMAIL, "nama": NAMA, "password_hash": hash_password(SANDI)}
    )
    clock = [now]
    return AuthService(store, now=lambda: clock[0]), store, clock


def _fail(auth, times: int, clock) -> None:
    for _ in range(times):
        with pytest.raises(OperatorError):
            auth.login(EMAIL, WRONG)
        clock[0] += 1


def test_the_right_password_opens_a_session_that_names_its_operator(tmp_path):
    auth, _, _ = _auth(tmp_path)

    token, operator = auth.login(EMAIL, SANDI)

    assert (operator["nama"], operator["email"]) == (NAMA, EMAIL)
    assert auth.current(token)["nama"] == NAMA


def test_an_account_pulled_from_autoerp_signs_in_without_asking_autoerp(tmp_path):
    """The whole offline design in one test: the hash AutoERP wrote is verified here,
    with no client and no network in the service at all."""
    auth, store, _ = _auth(tmp_path)
    store.upsert_operator_erp(
        {
            "email": "sari@pks.test",
            "nama": "Bu Sari",
            "password_hash": ERP_HASH,
            "erp_name": "sari@pks.test",
            "active": 1,
        }
    )

    token, operator = auth.login("sari@pks.test", SANDI)

    assert operator["nama"] == "Bu Sari"
    assert auth.current(token) is not None


def test_the_email_can_be_typed_any_way_the_operator_types_it(tmp_path):
    """An outdoor touchscreen with autocapitalisation would otherwise refuse a correct
    password, and the screen would say the password was wrong."""
    auth, _, _ = _auth(tmp_path)

    token, _ = auth.login("  BUDI@PKS.test ", SANDI)

    assert auth.current(token) is not None


def test_a_wrong_password_says_nothing_about_which_part_was_wrong(tmp_path):
    """One answer for a wrong password, an unknown account and a switched-off one: a
    shared screen must not let anyone map out who exists."""
    auth, store, _ = _auth(tmp_path)
    store.upsert_operator_lokal(
        {"email": "mati@pks.test", "nama": "Sudah Keluar", "password_hash": hash_password(SANDI)}
    )
    store.set_operator_status(operator_id_for("mati@pks.test"), "off")

    codes = set()
    for email, sandi in ((EMAIL, WRONG), ("tidak@ada.test", SANDI), ("mati@pks.test", SANDI)):
        with pytest.raises(OperatorError) as refused:
            auth.login(email, sandi)
        codes.add(refused.value.code)

    assert codes == {SANDI_SALAH}


def test_an_oversized_password_never_reaches_the_hash(tmp_path, monkeypatch):
    """Hashing is deliberately slow. A request body with a megabyte "password" must be
    turned away before it gets there — and still count as a wrong try."""
    auth, store, _ = _auth(tmp_path)
    hashed = []
    monkeypatch.setattr(
        "palmgrade.services.auth_service.verify_password",
        lambda *args: hashed.append(args) or False,
    )

    with pytest.raises(OperatorError) as refused:
        auth.login(EMAIL, "9" * 100_000)

    assert refused.value.code == SANDI_SALAH
    assert hashed == []
    assert store.operator(operator_id_for(EMAIL))["gagal_count"] == 1


def test_an_empty_password_is_refused_and_counted(tmp_path):
    """An account whose hash was never set (created in AutoERP, password still blank)
    must not be openable by sending nothing."""
    auth, store, _ = _auth(tmp_path)
    store.upsert_operator_erp(
        {"email": "baru@pks.test", "nama": "Belum Diisi", "password_hash": "", "active": 1}
    )

    with pytest.raises(OperatorError):
        auth.login("baru@pks.test", "")

    assert store.operator(operator_id_for("baru@pks.test"))["gagal_count"] == 1


def test_five_wrong_passwords_shut_sign_in_and_the_answer_says_for_how_long(tmp_path):
    auth, _, clock = _auth(tmp_path)

    _fail(auth, 5, clock)

    with pytest.raises(OperatorError) as locked:
        auth.login(EMAIL, SANDI)
    assert locked.value.code == TERKUNCI
    assert locked.value.params["detik"] > 0


def test_the_right_password_gets_in_once_the_lockout_has_run_out(tmp_path):
    """And the count goes back to zero, so a bad-glove evening does not follow the
    operator into the next shift."""
    auth, store, clock = _auth(tmp_path)
    _fail(auth, 5, clock)

    clock[0] += 120
    token, _ = auth.login(EMAIL, SANDI)

    assert auth.current(token) is not None
    assert store.operator(operator_id_for(EMAIL))["gagal_count"] == 0


def test_a_session_lasts_a_shift_and_not_a_day(tmp_path):
    auth, _, clock = _auth(tmp_path)
    token, _ = auth.login(EMAIL, SANDI)

    clock[0] += 12 * 60 * 60 - 60
    assert auth.current(token) is not None

    clock[0] += 120
    assert auth.current(token) is None


def test_signing_out_ends_the_session_at_once(tmp_path):
    auth, _, _ = _auth(tmp_path)
    token, _ = auth.login(EMAIL, SANDI)

    auth.logout(token)

    assert auth.current(token) is None


def test_no_cookie_and_a_made_up_cookie_are_both_nobody(tmp_path):
    auth, _, _ = _auth(tmp_path)

    assert auth.current(None) is None
    assert auth.current("tidak-pernah-ada") is None


def test_switching_an_operator_off_ends_the_session_they_still_hold(tmp_path):
    """How a leaver, or a password the whole shift has seen, is handled: one flag, and
    the screen in their hand stops writing."""
    auth, store, _ = _auth(tmp_path)
    token, _ = auth.login(EMAIL, SANDI)

    store.set_operator_status(operator_id_for(EMAIL), "off")

    assert auth.current(token) is None


def test_the_sign_in_screen_gets_no_hashes(tmp_path):
    """This listing is read before anyone is signed in, by any page on the LAN."""
    auth, _, _ = _auth(tmp_path)

    [operator] = auth.operators()

    assert set(operator) == {"id", "email", "nama", "status", "asal"}
