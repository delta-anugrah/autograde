"""Password and session rules for the operator console (Fase 4, plan §6.5).

Pure: hashing, password sanity, lockout arithmetic, token minting. No store, no HTTP.

**Accounts come from two places, and both are verified here, offline.** AutoERP owns the
real accounts — DocType `AutoGrade Operator`, added 2026-09-15 — and AutoGrade pulls them
down with the master data (§4.A). The console also writes its own local accounts: the
built-in one and the support account, which exist so a mill that has never reached the
internet can still be opened.

That split is why there are two schemes:

- `pbkdf2_sha256`, written by AutoERP's passlib context. Verified here with `hashlib`
  alone, so pulling accounts costs no new dependency at the mill.
- `scrypt`, written by this build for local accounts, which costs more to guess.

An operator must be able to sign in while the line is offline, so nothing here asks
AutoERP anything at login time — only the hash pulled earlier is consulted. Each stored
hash carries its own parameters, so the cost can be raised later without invalidating the
rows written now.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid

from .operator_error import SANDI_PENDEK, InvalidInput

PASSWORD_MIN_LENGTH = 8
"""The floor palmgrade-api already enforced; AutoERP's DocType refuses shorter too.

No character classes on purpose. A rule that demands symbols on an outdoor touchscreen
gets satisfied by writing the password on the monitor, which is a real loss of security
traded for an appearance of it.
"""

SESSION_TTL_S = 12 * 60 * 60
"""One full shift plus the handover, so a screen is not locked mid-load."""

_SCHEME = "scrypt"
# Interactive cost, ~100 ms on the mill PC; the gate is rate-limited on top.
# `n` must stay a power of two.
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
_SALT_BYTES = 16

_PBKDF2_SCHEME = "pbkdf2-sha256"
_PBKDF2_MIN_ROUNDS = 1000
"""Below this the pull is handing us a hash not worth honouring; refuse rather than
accept a cost an attacker can burn through."""

_LOCK_AFTER = 5
_LOCK_BASE_S = 60
_LOCK_MAX_S = 900


def operator_id_for(email: str) -> str:
    """The email is the account. AutoERP names the DocType by it too, so a row pulled
    from ERP lands on the same id as the local row typed for the same person — they
    adopt each other instead of becoming two accounts (same trick as trucks, §4.B)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"operator:{normalise_email(email)}"))


def normalise_email(email: str) -> str:
    """Lowercased and trimmed, matching what the DocType's `validate` stores."""
    return " ".join(str(email or "").split()).lower()


def normalise_nama(full_name: str) -> str:
    return " ".join(str(full_name or "").split())


def check_password_format(password: str) -> None:
    """Raise unless the password clears the shared minimum length."""
    if len(password or "") < PASSWORD_MIN_LENGTH:
        raise InvalidInput(SANDI_PENDEK, f"Sandi minimal {PASSWORD_MIN_LENGTH} karakter")


def hash_password(password: str) -> str:
    """`scheme$n$r$p$salt$hash` — per-row salt, parameters travel with the hash."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "$".join((_SCHEME, str(_N), str(_R), str(_P), salt.hex(), digest.hex()))


def verify_password(password: str, stored: str) -> bool:
    """Check a password against either scheme. False, never an exception.

    A row this build cannot read has to fail shut: the hash arrives from a pull or from
    disk, and both are data that can be truncated or edited.
    """
    text = str(stored or "")
    if text.startswith(f"${_PBKDF2_SCHEME}$"):
        return _verify_pbkdf2(password, text)
    return _verify_scrypt(password, text)


def _verify_scrypt(password: str, stored: str) -> bool:
    """Only the parameters this build writes are accepted.

    The row is data and data can be edited: trusting the cost it names would let a
    tampered row downgrade to a hash anyone can brute-force, or name one that eats the
    PC's memory on every sign-in. Raising the cost later means accepting both sets here,
    deliberately.
    """
    try:
        scheme, n, r, p, salt_hex, want = stored.split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(want)
    except ValueError:
        return False
    if (scheme, n, r, p) != (_SCHEME, str(_N), str(_R), str(_P)):
        return False
    if len(salt) != _SALT_BYTES or len(expected) != _DKLEN:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return hmac.compare_digest(digest, expected)


def _verify_pbkdf2(password: str, stored: str) -> bool:
    """Verify AutoERP's `$pbkdf2-sha256$rounds$salt$digest` with the standard library.

    Unlike the local scheme, the rounds named by the row are honoured — AutoERP owns
    this cost and may raise it, and we would otherwise lock out every account the moment
    it did. Only the floor is enforced.
    """
    try:
        _, scheme, rounds_text, salt_b64, digest_b64 = stored.split("$")
        rounds = int(rounds_text)
        salt = _b64_decode(salt_b64)
        expected = _b64_decode(digest_b64)
    except ValueError:
        return False
    if scheme != _PBKDF2_SCHEME or rounds < _PBKDF2_MIN_ROUNDS or not expected:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds, dklen=len(expected))
    return hmac.compare_digest(digest, expected)


def _b64_decode(text: str) -> bytes:
    """passlib writes base64 in its own dialect: `.` where the standard alphabet has
    `+`, and the `=` padding stripped. Feeding it to `base64` untranslated raises on
    some hashes and silently mismatches on others — an operator whose password is right
    being told it is wrong, for one account in sixty."""
    padded = text.replace(".", "+") + "=" * (-len(text) % 4)
    return base64.b64decode(padded, validate=True)


def lockout_seconds_left(fail_count: int, *, last_failed_at: float | None, now: float) -> int:
    """How long the keypad stays shut after wrong PINs.

    Doubles with every further mistake past the allowance, capped: guessing six digits
    must cost real time, but a shift locked out by a wet glove cannot be made to wait
    out the night.
    """
    if fail_count < _LOCK_AFTER or last_failed_at is None:
        return 0
    wait = min(_LOCK_BASE_S * 2 ** (fail_count - _LOCK_AFTER), _LOCK_MAX_S)
    return max(0, int(last_failed_at + wait - now))


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
