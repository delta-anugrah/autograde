"""Sign-in rules for the operator console (Fase 4, plan §6.5).

Pure: no store, no HTTP. The password is the only thing between a shared outdoor screen
and the numbers that get paid, so the rules live here where they are cheap to test — how
a password is stored, what counts as a usable one, how an account is identified, and how
long sign-in stays shut after repeated wrong tries.

The two hash schemes themselves are pinned in `test_password_schemes.py`.
"""

from __future__ import annotations

import hashlib

import pytest

from palmgrade.domain.operator_auth import (
    check_password_format,
    hash_password,
    lockout_seconds_left,
    new_session_token,
    normalise_email,
    operator_id_for,
    verify_password,
)
from palmgrade.domain.operator_error import InvalidInput

SANDI = "sawit2026"


def test_the_same_password_stored_twice_gives_two_different_hashes():
    """Per-row salt: two operators who both pick the mill's name and the year must not
    share a hash, or one readable row would give away both."""
    assert hash_password(SANDI) != hash_password(SANDI)


def test_a_password_verifies_against_its_own_hash_and_nothing_else():
    stored = hash_password(SANDI)

    assert verify_password(SANDI, stored)
    assert not verify_password("sawit2027", stored)


def test_a_hash_this_build_cannot_read_is_refused_not_trusted():
    """A row written by another scheme (or hand-edited to plain text) must fail shut."""
    assert not verify_password(SANDI, SANDI)
    assert not verify_password(SANDI, "")


def test_a_scrypt_hash_with_parameters_this_build_never_writes_is_refused(
):
    """The row is data, and data can be edited. Trusting the cost it names lets a
    tampered row downgrade to a hash anyone can brute-force — or name a cost that eats
    the PC's memory on every sign-in.

    AutoERP's own scheme is the deliberate exception: it owns that cost and may raise
    it, so its rounds are honoured above a floor (`test_password_schemes.py`).
    """
    salt = bytes(16)
    weak = hashlib.scrypt(SANDI.encode(), salt=salt, n=4, r=1, p=1, dklen=32)

    assert not verify_password(SANDI, f"scrypt$4$1$1${salt.hex()}${weak.hex()}")


def test_a_password_must_clear_eight_characters():
    check_password_format(SANDI)  # no raise

    for bad in ("sawit12", "1234567", ""):
        with pytest.raises(InvalidInput):
            check_password_format(bad)


def test_anything_at_least_eight_long_is_accepted():
    """No character classes on purpose: a rule demanding symbols on an outdoor
    touchscreen gets satisfied by writing the password on the monitor."""
    for fine in ("aaaaaaaa", "12345678", "pak budi sawit"):
        check_password_format(fine)


def test_sign_in_stays_open_for_the_first_few_mistakes():
    """Gloves and rain: an operator gets room to mistype without being locked out."""
    assert lockout_seconds_left(4, last_failed_at=100.0, now=100.0) == 0


def test_five_wrong_passwords_shut_sign_in_for_a_minute():
    assert lockout_seconds_left(5, last_failed_at=100.0, now=100.0) == 60
    assert lockout_seconds_left(5, last_failed_at=100.0, now=130.0) == 30
    assert lockout_seconds_left(5, last_failed_at=100.0, now=161.0) == 0


def test_every_further_wrong_password_doubles_the_wait_up_to_a_cap():
    """Guessing has to cost real time, but a locked-out shift must not have to wait
    forever either."""
    assert lockout_seconds_left(6, last_failed_at=0.0, now=0.0) == 120
    assert lockout_seconds_left(7, last_failed_at=0.0, now=0.0) == 240
    assert lockout_seconds_left(30, last_failed_at=0.0, now=0.0) == 900


def test_session_tokens_are_unique_and_long_enough_to_not_be_guessed():
    tokens = {new_session_token() for _ in range(200)}

    assert len(tokens) == 200
    assert all(len(token) >= 32 for token in tokens)


def test_one_email_is_always_one_account():
    """The id comes from the email, and AutoERP names its DocType by the same address —
    so a pulled account lands on the row already typed here instead of beside it."""
    assert operator_id_for("budi@pks.test") == operator_id_for("  BUDI@PKS.test  ")
    assert operator_id_for("budi@pks.test") != operator_id_for("budiman@pks.test")


def test_an_email_is_trimmed_and_lower_cased_the_way_autoerp_stores_it():
    """AutoERP's DocType normalises before naming; if this drifted from that, one person
    would end up with two accounts and two passwords."""
    assert normalise_email("  Budi@PKS.Test ") == "budi@pks.test"
    assert normalise_email(None) == ""
