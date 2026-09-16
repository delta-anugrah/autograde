"""The two local accounts every AutoGrade image carries (Fase 4, plan §6.5).

A mill PC gets installed before it has ever reached the internet, and AutoERP's accounts
arrive only with the first pull. Without something already on disk the console would be
a locked screen on the day it is most needed, so each image seeds two accounts:

- `operator@autograde.local` — the mill's own, handed to the shift
- `support@autograde.local` — ours, for a developer arriving over AnyDesk

**Only the hash is baked, never the password.** The build passes
`CONSOLE_DEFAULT_HASH` / `CONSOLE_SUPPORT_HASH`, so no raw password enters the image, its
layers, or its build log — a factory PC is reachable over AnyDesk, and an image layer is
readable by anyone holding the image.

Passwords differ per mill (operator's decision, 2026-09-15), generated at install time.
The emails are the same everywhere so support never has to ask which address a mill used.
"""

from __future__ import annotations

import logging

from ..domain.operator_auth import operator_id_for
from ..domain.role import ROLE_SUPPORT
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

# Names kept as-is (not translated): scripts/hash-sandi.py and its test import
# these two constants directly, outside this branch's scope.
EMAIL_BAWAAN = "operator@autograde.local"
EMAIL_SUPPORT = "support@autograde.local"

_DEFAULT_NAME = "Operator Pabrik"
_SUPPORT_NAME = "Support AutoGrade"


def seed_default_accounts(
    store: ConsoleStore, *, hash_bawaan: str, hash_support: str
) -> list[str]:
    """Create whichever of the two accounts is missing. Returns the emails created.

    Never touches an account that already exists — not its password, not its status.
    A container restarts for all sorts of reasons, and a restart that quietly restored
    the factory password would undo every password the mill had changed, on exactly the
    accounts whose passwords are identical across images.
    """
    created = []
    for email, full_name, password_hash in (
        (EMAIL_BAWAAN, _DEFAULT_NAME, hash_bawaan),
        (EMAIL_SUPPORT, _SUPPORT_NAME, hash_support),
    ):
        if _create_if_missing(store, email, full_name, password_hash):
            created.append(email)
    _ensure_support_role(store)
    return created


def _ensure_support_role(store: ConsoleStore) -> None:
    """Promote the support account, including on a PC that had it before the
    `role` column existed. Touches only `role`, never the password — same
    reason the seed never re-upserts an existing account."""
    row = store.operator_by_email(EMAIL_SUPPORT)
    if row is not None and row["role"] != ROLE_SUPPORT:
        store.set_role(row["id"], ROLE_SUPPORT)


def _create_if_missing(
    store: ConsoleStore, email: str, full_name: str, password_hash: str
) -> bool:
    if not password_hash:
        # A build with no hash, or a `.env` nobody filled in. Skipped silently: this is
        # the normal state of a mill whose accounts all come from AutoERP.
        return False

    if not _hash_is_readable(password_hash):
        # Compose eats `$` (`$$` for a literal one), so a truncated hash is a real
        # accident rather than a theory. An account nobody can sign into but that shows
        # on screen is worse than no account, so it is refused and said out loud.
        logger.error(
            "Default account %s not created: hash is not readable. "
            "Set CONSOLE_DEFAULT_HASH/CONSOLE_SUPPORT_HASH to a hash, not a raw password; "
            "in docker-compose write $$ for one literal $.",
            email,
        )
        return False

    if store.operator(operator_id_for(email)) is not None:
        return False

    store.upsert_operator_manual({"email": email, "full_name": full_name, "password_hash": password_hash})
    logger.info("Default account %s created from the hash baked into the image", email)
    return True


def _hash_is_readable(password_hash: str) -> bool:
    """Only the two shapes this build can verify are accepted.

    A raw password passed by mistake fails here, which is the point: it must never end
    up baked into an image. So does a hash Compose truncated at the first `$`.
    """
    return password_hash.startswith(("$pbkdf2-sha256$", "scrypt$"))
