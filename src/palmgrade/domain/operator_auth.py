"""PIN and session rules for the operator console (Fase 4, plan §6.5).

Pure: hashing, PIN sanity, lockout arithmetic, token minting. No store, no HTTP.

**Local accounts, decided 2026-09-15.** AutoERP has no operator DocType, and the
password hashes Frappe holds for its own users live in `__Auth`, which it deliberately
never serves over REST — so there is nothing to pull today. An operator must also be
able to sign in while the line is offline, which rules out asking AutoERP at login time.
The stored hash carries its own parameters, so the cost can be raised later without
invalidating the rows written now.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

from .operator_error import PIN_FORMAT, PIN_LEMAH, InvalidInput

PIN_LENGTH = 6
SESSION_TTL_S = 12 * 60 * 60
"""One full shift plus the handover, so a screen is not locked mid-load."""

_SCHEME = "scrypt"
# Interactive cost, ~100 ms on the mill PC; the keypad is rate-limited on top.
# `n` must stay a power of two.
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
_SALT_BYTES = 16

_LOCK_AFTER = 5
_LOCK_BASE_S = 60
_LOCK_MAX_S = 900


def operator_id_for(nama: str) -> str:
    """One name is one operator, however it was typed when the account was made."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"operator:{normalise_nama(nama).lower()}"))


def normalise_nama(nama: str) -> str:
    return " ".join(str(nama or "").split())


def check_pin_format(pin: str) -> None:
    """Raise unless the PIN is usable on a screen the whole shift can see."""
    if len(pin or "") != PIN_LENGTH or not str(pin).isdigit():
        raise InvalidInput(PIN_FORMAT, f"PIN harus {PIN_LENGTH} angka")
    if _too_obvious(pin):
        raise InvalidInput(PIN_LEMAH, "PIN terlalu mudah ditebak")


def _too_obvious(pin: str) -> bool:
    """Repeated (`000000`) or a straight run (`123456`, `654321`) — the first tries."""
    digits = [int(d) for d in pin]
    steps = {digits[i + 1] - digits[i] for i in range(len(digits) - 1)}
    return steps in ({0}, {1}, {-1})


def hash_pin(pin: str) -> str:
    """`scheme$n$r$p$salt$hash` — per-row salt, parameters travel with the hash."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "$".join((_SCHEME, str(_N), str(_R), str(_P), salt.hex(), digest.hex()))


def verify_pin(pin: str, stored: str) -> bool:
    """False, never an exception: a row this build cannot read has to fail shut.

    Only the parameters this build writes are accepted. The row is data and data can be
    edited: trusting the cost it names would let a tampered row downgrade to a hash
    anyone can brute-force, or name one that eats the PC's memory on every sign-in.
    Raising the cost later means accepting both sets here, deliberately.
    """
    try:
        scheme, n, r, p, salt_hex, want = str(stored).split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(want)
    except ValueError:
        return False
    if (scheme, n, r, p) != (_SCHEME, str(_N), str(_R), str(_P)):
        return False
    if len(salt) != _SALT_BYTES or len(expected) != _DKLEN:
        return False
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return hmac.compare_digest(digest, expected)


def lockout_seconds_left(gagal_count: int, *, last_failed_at: float | None, now: float) -> int:
    """How long the keypad stays shut after wrong PINs.

    Doubles with every further mistake past the allowance, capped: guessing six digits
    must cost real time, but a shift locked out by a wet glove cannot be made to wait
    out the night.
    """
    if gagal_count < _LOCK_AFTER or last_failed_at is None:
        return 0
    wait = min(_LOCK_BASE_S * 2 ** (gagal_count - _LOCK_AFTER), _LOCK_MAX_S)
    return max(0, int(last_failed_at + wait - now))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
