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
from ..domain.peran import PERAN_SUPPORT
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

EMAIL_BAWAAN = "operator@autograde.local"
EMAIL_SUPPORT = "support@autograde.local"

_NAMA_BAWAAN = "Operator Pabrik"
_NAMA_SUPPORT = "Support AutoGrade"


def seed_akun_bawaan(
    store: ConsoleStore, *, hash_bawaan: str, hash_support: str
) -> list[str]:
    """Create whichever of the two accounts is missing. Returns the emails created.

    Never touches an account that already exists — not its password, not its status.
    A container restarts for all sorts of reasons, and a restart that quietly restored
    the factory password would undo every password the mill had changed, on exactly the
    accounts whose passwords are identical across images.
    """
    dibuat = []
    for email, nama, hash_sandi in (
        (EMAIL_BAWAAN, _NAMA_BAWAAN, hash_bawaan),
        (EMAIL_SUPPORT, _NAMA_SUPPORT, hash_support),
    ):
        if _buat_kalau_belum_ada(store, email, nama, hash_sandi):
            dibuat.append(email)
    _pastikan_peran_support(store)
    return dibuat


def _pastikan_peran_support(store: ConsoleStore) -> None:
    """Naikkan akun support, juga di PC yang sudah punya akun itu sejak sebelum
    kolom `peran` ada.

    Terpisah dari pembuatan dan hanya menyentuh `peran`: akun yang sudah ada tidak
    boleh kehilangan sandi yang sudah diganti pabrik — alasan yang sama dengan
    kenapa seed tidak pernah meng-upsert ulang.
    """
    row = store.operator_by_email(EMAIL_SUPPORT)
    if row is not None and row["peran"] != PERAN_SUPPORT:
        store.set_peran(row["id"], PERAN_SUPPORT)


def _buat_kalau_belum_ada(
    store: ConsoleStore, email: str, nama: str, hash_sandi: str
) -> bool:
    if not hash_sandi:
        # A build with no hash, or a `.env` nobody filled in. Skipped silently: this is
        # the normal state of a mill whose accounts all come from AutoERP.
        return False

    if not _hash_terbaca(hash_sandi):
        # Compose eats `$` (`$$` for a literal one), so a truncated hash is a real
        # accident rather than a theory. An account nobody can sign into but that shows
        # on screen is worse than no account, so it is refused and said out loud.
        logger.error(
            "Akun bawaan %s tidak dibuat: hash tidak terbaca. "
            "Isi CONSOLE_DEFAULT_HASH/CONSOLE_SUPPORT_HASH dengan hash, bukan sandi; "
            "di docker-compose tulis $$ untuk satu $.",
            email,
        )
        return False

    if store.operator(operator_id_for(email)) is not None:
        return False

    store.upsert_operator_lokal({"email": email, "nama": nama, "password_hash": hash_sandi})
    logger.info("Akun bawaan %s dibuat dari hash yang ditanam di image", email)
    return True


def _hash_terbaca(hash_sandi: str) -> bool:
    """Only the two shapes this build can verify are accepted.

    A raw password passed by mistake fails here, which is the point: it must never end
    up baked into an image. So does a hash Compose truncated at the first `$`.
    """
    return hash_sandi.startswith(("$pbkdf2-sha256$", "scrypt$"))
