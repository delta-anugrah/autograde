"""PIN rules for the operator console (Fase 4, plan §6.5).

Pure: no store, no HTTP. The PIN is the only thing between a shared outdoor screen and
the numbers that get paid, so the rules live here where they are cheap to test — how a
PIN is stored, what counts as a usable one, and how long the keypad stays shut after
repeated wrong tries.
"""

from __future__ import annotations

import hashlib

import pytest

from palmgrade.domain.operator_auth import (
    check_pin_format,
    hash_pin,
    lockout_seconds_left,
    new_session_token,
    operator_id_for,
    verify_pin,
)
from palmgrade.domain.operator_error import InvalidInput

PIN = "142536"


def test_the_same_pin_stored_twice_gives_two_different_hashes():
    """Per-row salt: two operators who both pick 1-4-2-5-3-6 must not share a hash, or
    one readable row would give away both."""
    assert hash_pin(PIN) != hash_pin(PIN)


def test_a_pin_verifies_against_its_own_hash_and_nothing_else():
    stored = hash_pin(PIN)

    assert verify_pin(PIN, stored)
    assert not verify_pin("142537", stored)


def test_a_hash_this_build_cannot_read_is_refused_not_trusted():
    """A row written by another scheme (or hand-edited to plain text) must fail shut."""
    assert not verify_pin(PIN, "142536")
    assert not verify_pin(PIN, "")


def test_a_hash_with_parameters_this_build_never_writes_is_refused_even_when_it_matches():
    """The row is data, and data can be edited. Trusting the cost it names lets a
    tampered row downgrade to a hash anyone can brute-force — or name a cost that eats
    the PC's memory on every sign-in."""
    salt = bytes(16)
    weak = hashlib.scrypt(PIN.encode(), salt=salt, n=4, r=1, p=1, dklen=32)

    assert not verify_pin(PIN, f"scrypt$4$1$1${salt.hex()}${weak.hex()}")


def test_a_pin_must_be_exactly_six_digits():
    check_pin_format(PIN)  # no raise

    for bad in ("12345", "1234567", "14253a", "1425 6", ""):
        with pytest.raises(InvalidInput):
            check_pin_format(bad)


def test_the_pins_everyone_tries_first_are_refused():
    """On a screen the whole shift can see, `000000` and `123456` are not secrets."""
    for obvious in ("000000", "111111", "123456", "654321"):
        with pytest.raises(InvalidInput):
            check_pin_format(obvious)


def test_the_keypad_stays_open_for_the_first_few_mistakes():
    """Gloves and rain: an operator gets room to mistype without being locked out."""
    assert lockout_seconds_left(4, last_failed_at=100.0, now=100.0) == 0


def test_five_wrong_pins_shut_the_keypad_for_a_minute():
    assert lockout_seconds_left(5, last_failed_at=100.0, now=100.0) == 60
    assert lockout_seconds_left(5, last_failed_at=100.0, now=130.0) == 30
    assert lockout_seconds_left(5, last_failed_at=100.0, now=161.0) == 0


def test_every_further_wrong_pin_doubles_the_wait_up_to_a_cap():
    """Guessing six digits has to cost real time, but a locked-out shift must not have
    to wait forever either."""
    assert lockout_seconds_left(6, last_failed_at=0.0, now=0.0) == 120
    assert lockout_seconds_left(7, last_failed_at=0.0, now=0.0) == 240
    assert lockout_seconds_left(30, last_failed_at=0.0, now=0.0) == 900


def test_session_tokens_are_unique_and_long_enough_to_not_be_guessed():
    tokens = {new_session_token() for _ in range(200)}

    assert len(tokens) == 200
    assert all(len(token) >= 32 for token in tokens)


def test_one_operator_name_is_always_one_id():
    """The id comes from the name, so adding the same operator twice updates the row
    instead of leaving two people with one face on the keypad."""
    assert operator_id_for("Pak Budi") == operator_id_for("  pak budi  ")
    assert operator_id_for("Pak Budi") != operator_id_for("Pak Bud")
