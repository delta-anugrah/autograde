"""Two hash schemes live side by side, on purpose (Fase 4).

An operator account can come from two places, and the console has to verify both **at the
mill**, with no network:

- **AutoERP** owns the real accounts and hashes them with Frappe's passlib context, which
  is `pbkdf2_sha256`. That hash is pulled down with the master data.
- **The console itself** writes the local accounts (the built-in and the support one) with
  scrypt, which costs more to guess.

`pbkdf2_sha256` is in Python's standard library, so reading AutoERP's hash needs no new
dependency. The catch this pins: passlib writes base64 in its own dialect — `.` instead of
`+`, and no padding. Decoding it with plain base64 fails quietly, and a sign-in that
should work just says "wrong password".

The vectors below were produced by the real bench:
`bench --site pks.localhost execute frappe.utils.password.passlibctx.hash`
"""

from __future__ import annotations

import pytest

from palmgrade.domain.operator_auth import (
    PASSWORD_MIN_LENGTH,
    check_password_format,
    hash_password,
    verify_password,
)
from palmgrade.domain.operator_error import InvalidInput

PASSWORD = "sawit2026"
# Real output of Frappe's passlibctx.hash("sawit2026") on the pks.localhost bench.
FRAPPE_HASH = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"

# The same password, hashed again on the same bench. The salt is random, so only some
# hashes land a `.` or a `/` in their base64 — which is exactly why the dialect bug
# hides: it breaks roughly half the accounts and leaves the rest working.
FRAPPE_HASH_WITH_DOT = "$pbkdf2-sha256$29000$GgPAeE9pTSnlHMOYc25NqQ$xm8TMCM65o6kxwljP.UukzwU7RMx9CUur3dwsgfNoAQ"
FRAPPE_HASH_WITH_DOT_AND_SLASH = (
    "$pbkdf2-sha256$29000$DoEwxjgHIARASEnpXUsJwQ$CXzaoeAsIJjYHTRtgAdQ4xqA0qs.vpl5ABlQrG7YE/U"
)


def test_a_hash_written_by_autoerp_verifies_at_the_mill():
    """The whole offline story rests on this one line: no passlib, no network."""
    assert verify_password(PASSWORD, FRAPPE_HASH)


def test_the_wrong_password_fails_against_an_autoerp_hash():
    assert not verify_password("salah123", FRAPPE_HASH)


def test_the_passlib_base64_dialect_is_handled():
    """`.` where standard base64 puts `+`, padding stripped, `/` kept as itself.

    Decoded untranslated these mismatch, so the operator is told their password is wrong
    when it is not — for the half of accounts whose random salt happens to contain one.
    """
    assert verify_password(PASSWORD, FRAPPE_HASH_WITH_DOT)
    assert verify_password(PASSWORD, FRAPPE_HASH_WITH_DOT_AND_SLASH)

    assert not verify_password("salah123", FRAPPE_HASH_WITH_DOT)
    assert not verify_password("salah123", FRAPPE_HASH_WITH_DOT_AND_SLASH)


def test_a_local_account_is_hashed_with_scrypt_and_verifies():
    stored = hash_password(PASSWORD)

    assert stored.startswith("scrypt$")
    assert verify_password(PASSWORD, stored)
    assert not verify_password("salah123", stored)


def test_two_local_hashes_of_one_password_differ():
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_a_scheme_neither_side_writes_is_refused():
    """bcrypt is what the retiring palmgrade-api used. Accepting it here would mean
    carrying a third verifier nobody audits."""
    assert not verify_password(PASSWORD, "$2b$12$" + "a" * 53)
    assert not verify_password(PASSWORD, "argon2$whatever")
    assert not verify_password(PASSWORD, PASSWORD)
    assert not verify_password(PASSWORD, "")


def test_a_pbkdf2_hash_with_a_broken_body_is_refused_not_crashed():
    """Rows are data. A truncated or hand-edited hash has to fail shut, not raise."""
    for broken in (
        "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q",  # no digest
        "$pbkdf2-sha256$abc$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8",
        "$pbkdf2-sha512$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8",
    ):
        assert not verify_password(PASSWORD, broken), broken


def test_a_password_needs_eight_characters_and_nothing_else():
    """The floor palmgrade-api already enforced. No character classes: a rule that forces
    symbols onto an outdoor touchscreen ends up written on the monitor."""
    check_password_format("sawit123")
    check_password_format("aaaaaaaa")

    for bad in ("sawit12", "", "1234567"):
        with pytest.raises(InvalidInput):
            check_password_format(bad)


def test_the_minimum_is_the_one_the_old_system_used():
    assert PASSWORD_MIN_LENGTH == 8
