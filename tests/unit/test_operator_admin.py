"""Managing local operator accounts from the PC, not from the screen (Fase 4, §6.5).

There is deliberately no web lane for this: an account that can be created from the
console page is one anybody on the mill LAN can create. The command runs on the PC
itself — `make operator` — and this is the logic behind it.

Only local accounts are managed here. AutoERP owns the accounts it sends down, and this
must refuse to touch them: a password changed on the PC would be undone by the next
pull, so an operator told it worked would be locked out later, with nothing on screen
explaining why.
"""

from __future__ import annotations

import pytest

from palmgrade.domain.operator_auth import (
    new_session_token,
    operator_id_for,
    verify_password,
)
from palmgrade.domain.operator_error import InvalidInput
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.services.operator_admin import OperatorAdmin

EMAIL = "budi@pks.test"
NAMA = "Pak Budi"
SANDI = "sawit2026"
ERP_HASH = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"


def _admin(tmp_path) -> tuple[OperatorAdmin, ConsoleStore]:
    store = ConsoleStore(tmp_path / "console.db")
    return OperatorAdmin(store), store


def test_an_operator_added_can_sign_in_with_that_password(tmp_path):
    admin, store = _admin(tmp_path)

    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI)

    row = store.operator(operator_id_for(EMAIL))
    assert (row["status"], row["asal"], row["nama"]) == ("active", "lokal", NAMA)
    assert verify_password(SANDI, row["password_hash"])


def test_the_password_has_to_be_typed_the_same_twice(tmp_path):
    """Typed blind on a terminal; one slip would lock the operator out on day one."""
    admin, store = _admin(tmp_path)

    with pytest.raises(ValueError, match="tidak sama"):
        admin.add_or_reset(EMAIL, NAMA, SANDI, "sawit2027")

    assert store.operator(operator_id_for(EMAIL)) is None


def test_a_password_below_the_rule_is_refused_before_anything_is_stored(tmp_path):
    admin, store = _admin(tmp_path)

    with pytest.raises(InvalidInput):
        admin.add_or_reset(EMAIL, NAMA, "sawit12", "sawit12")

    assert store.operator(operator_id_for(EMAIL)) is None


def test_an_account_needs_an_email_because_that_is_what_gets_typed(tmp_path):
    admin, _ = _admin(tmp_path)

    for bad in ("   ", "pak-budi"):
        with pytest.raises(ValueError, match="email"):
            admin.add_or_reset(bad, NAMA, SANDI, SANDI)


def test_an_account_needs_a_name_the_screen_can_show(tmp_path):
    admin, _ = _admin(tmp_path)

    with pytest.raises(ValueError, match="nama"):
        admin.add_or_reset(EMAIL, "   ", SANDI, SANDI)


def test_the_email_is_stored_the_way_autoerp_stores_it(tmp_path):
    admin, store = _admin(tmp_path)

    admin.add_or_reset("  BUDI@PKS.test ", NAMA, SANDI, SANDI)

    assert store.operator(operator_id_for(EMAIL))["email"] == EMAIL


def test_adding_again_resets_the_password_and_ends_the_old_sessions(tmp_path):
    """The forgotten-password path, and the seen-password path: same command."""
    admin, store = _admin(tmp_path)
    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI)
    token = new_session_token()
    store.create_session(token, operator_id_for(EMAIL), now=1000.0, ttl_s=43200)

    admin.add_or_reset(EMAIL, NAMA, "sawit2027", "sawit2027")

    row = store.operator(operator_id_for(EMAIL))
    assert verify_password("sawit2027", row["password_hash"])
    assert not verify_password(SANDI, row["password_hash"])
    assert store.session(token, now=1000.0) is None


def test_an_account_autoerp_owns_cannot_be_rewritten_from_the_pc(tmp_path):
    """Refused out loud rather than quietly ignored: an operator told the new password
    works, whose old one still does, is worse off than one told to go to backoffice."""
    admin, store = _admin(tmp_path)
    store.upsert_operator_erp(
        {"email": EMAIL, "nama": NAMA, "password_hash": ERP_HASH, "erp_name": EMAIL, "active": 1}
    )

    with pytest.raises(ValueError, match="AutoERP"):
        admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI)

    assert store.operator(operator_id_for(EMAIL))["password_hash"] == ERP_HASH


def test_switching_an_operator_off_takes_them_off_the_screen(tmp_path):
    admin, store = _admin(tmp_path)
    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI)

    admin.switch_off(" BUDI@pks.test ")

    assert admin.listing() == []
    assert store.operator(operator_id_for(EMAIL))["status"] == "off"


def test_an_account_autoerp_owns_can_still_be_switched_off_here(tmp_path):
    """Someone at the mill has to be able to shut out a leaver before the next pull.
    The pull puts it back if AutoERP still says active — the owner winning, correctly."""
    admin, store = _admin(tmp_path)
    store.upsert_operator_erp(
        {"email": EMAIL, "nama": NAMA, "password_hash": ERP_HASH, "erp_name": EMAIL, "active": 1}
    )

    admin.switch_off(EMAIL)

    assert store.operator(operator_id_for(EMAIL))["status"] == "off"


def test_switching_off_an_email_nobody_has_says_so(tmp_path):
    """A typo must not look like success while the real account stays live."""
    admin, _ = _admin(tmp_path)

    with pytest.raises(ValueError, match="tidak ada"):
        admin.switch_off("budiman@pks.test")


def test_the_listing_shows_where_each_account_came_from(tmp_path):
    """`make operator AKSI=daftar` is where someone checks why a password will not
    change: the row says `erp`, so it is backoffice's to reset."""
    admin, store = _admin(tmp_path)
    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI)
    store.upsert_operator_erp(
        {
            "email": "sari@pks.test",
            "nama": "Bu Sari",
            "password_hash": ERP_HASH,
            "erp_name": "sari@pks.test",
            "active": 1,
        }
    )

    asal = {row["email"]: row["asal"] for row in admin.listing()}

    assert asal == {EMAIL: "lokal", "sari@pks.test": "erp"}


# ------------------------------------------------------------------- peran
#
# The gap these cover: a mill whose accounts were all made by `make operator`
# before it knew about roles ends up with nobody able to reach the developer
# screens, and no local way back in. `AKSI=peran` (via `set_peran`) and a role
# on `AKSI=tambah` (via `add_or_reset`) are the two ways out.


def test_a_role_given_on_add_lands_in_the_column(tmp_path):
    admin, store = _admin(tmp_path)

    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI, peran="support")

    assert store.operator(operator_id_for(EMAIL))["peran"] == "support"


def test_an_unrecognised_role_on_add_falls_back_to_operator(tmp_path):
    """A typo in PERAN must not land on the column unchecked — the column
    gates the piston screen, same reasoning as `ConsoleStore.set_peran`."""
    admin, store = _admin(tmp_path)

    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI, peran="admin")

    assert store.operator(operator_id_for(EMAIL))["peran"] == "operator"


def test_omitting_the_role_on_add_promotes_nobody(tmp_path):
    """The default `make operator` run — no PERAN typed — must never be the
    thing that silently creates a second support account."""
    admin, store = _admin(tmp_path)

    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI)

    assert store.operator(operator_id_for(EMAIL))["peran"] == "operator"


def test_a_role_on_add_never_touches_an_existing_accounts_role(tmp_path):
    """`add_or_reset` is also the forgotten-password path. A password reset run
    with no PERAN typed must not silently demote a support account back to
    plain operator."""
    admin, store = _admin(tmp_path)
    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI, peran="support")

    _, disahkan = admin.add_or_reset(EMAIL, NAMA, "sawit2027", "sawit2027")

    assert disahkan == "support"
    assert store.operator(operator_id_for(EMAIL))["peran"] == "support"


def test_set_peran_changes_an_existing_accounts_role(tmp_path):
    admin, store = _admin(tmp_path)
    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI)

    disahkan = admin.set_peran(EMAIL, "support")

    assert disahkan == "support"
    assert store.operator(operator_id_for(EMAIL))["peran"] == "support"


def test_set_peran_also_falls_back_to_operator_on_an_unknown_value(tmp_path):
    admin, store = _admin(tmp_path)
    admin.add_or_reset(EMAIL, NAMA, SANDI, SANDI, peran="support")

    disahkan = admin.set_peran(EMAIL, "admin")

    assert disahkan == "operator"
    assert store.operator(operator_id_for(EMAIL))["peran"] == "operator"


def test_set_peran_on_an_email_nobody_has_says_so(tmp_path):
    """Same reasoning as `switch_off`: a typo must not read as success."""
    admin, _ = _admin(tmp_path)

    with pytest.raises(ValueError, match="tidak ada"):
        admin.set_peran("budiman@pks.test", "support")
