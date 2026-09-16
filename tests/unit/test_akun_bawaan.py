"""The two accounts baked into every AutoGrade image (Fase 4, plan §6.5).

A mill PC can be installed before it has ever reached the internet, and AutoERP's
accounts arrive only with the first pull. Without something already on the disk there
would be nothing to sign in with, and the console would be a locked screen on the day it
is most needed.

So each image carries two local accounts:

- `operator@autograde.local` — the mill's own account, handed to the shift
- `support@autograde.local` — ours, for a developer coming in over AnyDesk

**Only the hash is baked, never the password.** The build takes
`CONSOLE_DEFAULT_HASH` / `CONSOLE_SUPPORT_HASH`, so a raw password never enters the
image, its layers, or its build log — a factory PC is reachable over AnyDesk, and an
image layer is readable by anyone who has one.

Per the operator's decision (2026-09-15) the passwords are **different per mill**,
generated at install time. The emails are fixed across images so support does not have
to ask which address a given mill used.

The rule that matters most here is the last one: seeding must never overwrite an account
that already exists. A container restarts for all sorts of reasons, and a restart that
silently restored the factory password would undo every password the mill had changed —
quietly, and exactly on the accounts that are the same on every image.
"""

from __future__ import annotations

from palmgrade.domain.operator_auth import hash_password, operator_id_for, verify_password
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.akun_bawaan import (
    EMAIL_BAWAAN,
    EMAIL_SUPPORT,
    seed_default_accounts,
)

PASSWORD_DEFAULT = "pabrik2026"
PASSWORD_SUPPORT = "support2026"


def _store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _seed(store, *, default=PASSWORD_DEFAULT, support=PASSWORD_SUPPORT):
    return seed_default_accounts(
        store,
        hash_bawaan=hash_password(default) if default else "",
        hash_support=hash_password(support) if support else "",
    )


def test_both_accounts_are_created_and_can_sign_in(tmp_path):
    store = _store(tmp_path)

    created = _seed(store)

    assert sorted(created) == [EMAIL_BAWAAN, EMAIL_SUPPORT]
    for email, password in ((EMAIL_BAWAAN, PASSWORD_DEFAULT), (EMAIL_SUPPORT, PASSWORD_SUPPORT)):
        row = store.operator_by_email(email)
        assert row["status"] == "active"
        assert row["origin"] == "lokal", "the default account belongs to this PC, not to AutoERP"
        assert verify_password(password, row["password_hash"])


def test_the_email_is_the_same_on_every_image(tmp_path):
    """Support must never need to ask 'what's your email?' before reaching any mill."""
    assert EMAIL_BAWAAN == "operator@autograde.local"
    assert EMAIL_SUPPORT == "support@autograde.local"


def test_seeding_a_second_time_overwrites_nothing(tmp_path):
    """A container restart is routine. If seeding overwrote it, a password the mill
    already changed would silently revert to the factory default — on exactly the
    accounts whose password is the same across every image."""
    store = _store(tmp_path)
    _seed(store)
    store.upsert_operator_manual(
        {
            "email": EMAIL_BAWAAN,
            "full_name": "Pak Budi",
            "password_hash": hash_password("sudahdiganti2026"),
        }
    )

    created = _seed(store)

    assert created == []
    row = store.operator_by_email(EMAIL_BAWAAN)
    assert verify_password("sudahdiganti2026", row["password_hash"])
    assert not verify_password(PASSWORD_DEFAULT, row["password_hash"])


def test_a_switched_off_account_is_not_revived_by_a_restart(tmp_path):
    """Switching off the default account is a deliberate choice — usually because the
    mill already has its own account from AutoERP. A restart must not undo it."""
    store = _store(tmp_path)
    _seed(store)
    store.set_operator_status(operator_id_for(EMAIL_BAWAAN), "off")

    _seed(store)

    assert store.operator_by_email(EMAIL_BAWAAN)["status"] == "off"


def test_an_empty_hash_means_the_account_is_not_created(tmp_path):
    """A build with no hash (or a `.env` nobody filled in) must not produce an
    account with no password that anyone could sign into."""
    store = _store(tmp_path)

    created = seed_default_accounts(store, hash_bawaan="", hash_support="")

    assert created == []
    assert store.operators() == []


def test_an_unreadable_hash_is_refused_not_stored(tmp_path):
    """Compose eats `$` (`$$` for one literal `$`), so a truncated hash is a real
    event, not a theory. An account with a broken hash = one nobody can sign into
    but that still shows on screen; better not created at all."""
    store = _store(tmp_path)

    created = seed_default_accounts(
        store, hash_bawaan="pbkdf2-sha256$29000$terpotong", hash_support="sandi-mentah"
    )

    assert created == []
    assert store.operators() == []


def test_a_raw_password_is_never_accepted_as_a_hash(tmp_path):
    """If this passed, a raw password would end up baked into the image — the exact
    thing this whole design avoids."""
    store = _store(tmp_path)

    seed_default_accounts(store, hash_bawaan=PASSWORD_DEFAULT, hash_support=PASSWORD_SUPPORT)

    assert store.operators() == []


def test_the_support_account_is_still_created_even_if_the_default_one_is_not(tmp_path):
    """The two accounts are independent: one hash left empty must not also disable
    the other's sign-in path."""
    store = _store(tmp_path)

    created = seed_default_accounts(store, hash_bawaan="", hash_support=hash_password(PASSWORD_SUPPORT))

    assert created == [EMAIL_SUPPORT]
    assert store.operator_by_email(EMAIL_BAWAAN) is None
    assert verify_password(PASSWORD_SUPPORT, store.operator_by_email(EMAIL_SUPPORT)["password_hash"])


def test_an_autoerp_account_with_the_same_email_is_left_untouched(tmp_path):
    """If backoffice ever creates an AutoERP account with the same email, AutoERP
    wins — the same two-source rule as everywhere else (invariant 19)."""
    store = _store(tmp_path)
    erp_hash = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"
    store.upsert_operator_erp(
        {
            "email": EMAIL_SUPPORT,
            "full_name": "Support ERP",
            "password_hash": erp_hash,
            "erp_name": EMAIL_SUPPORT,
            "active": 1,
        }
    )

    _seed(store)

    row = store.operator_by_email(EMAIL_SUPPORT)
    assert (row["origin"], row["password_hash"]) == ("erp", erp_hash)


def test_the_support_account_is_created_with_the_support_role(tmp_path):
    store = _store(tmp_path)
    _seed(store)
    assert store.operator_by_email(EMAIL_SUPPORT)["role"] == "support"
    assert store.operator_by_email(EMAIL_BAWAAN)["role"] == "operator"


def test_an_old_support_account_is_promoted_without_touching_its_password(tmp_path):
    """A PC upgrading from before the `role` column must gain the role
    without its factory-set password reverting to the seed default."""
    store = _store(tmp_path)
    store.upsert_operator_manual(
        {"email": EMAIL_SUPPORT, "full_name": "Support", "password_hash": "scrypt$sandi-mill"}
    )
    _seed(store)
    row = store.operator_by_email(EMAIL_SUPPORT)
    assert row["role"] == "support"
    assert row["password_hash"] == "scrypt$sandi-mill"
