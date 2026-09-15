"""Operator accounts and their sessions in the console index (Fase 4, plan §6.5).

Accounts arrive from two places and the row remembers which (`asal`):

- `erp` — AutoERP's `AutoGrade Operator` DocType, pulled with the master data (§4.A).
  AutoERP owns these; backoffice creates them and sets the passwords.
- `lokal` — written on this PC by `make operator`: the built-in account and the support
  account, which is how a mill that has never reached the internet gets opened at all.

Neither source may overwrite the other's rows. That is the rule most of this file is
about, because getting it wrong is silent: a pull that flattens the local support account
locks the mill out precisely when the internet is down, and a CLI that overwrites an ERP
row makes the mill disagree with the ledger until someone notices.
"""

from __future__ import annotations

from palmgrade.domain.operator_auth import (
    hash_password,
    new_session_token,
    operator_id_for,
)
from palmgrade.repositories.console_repository import ConsoleStore

EMAIL = "budi@pks.test"
NAMA = "Pak Budi"
SANDI = "sawit2026"
# What AutoERP's passlib context writes; the console verifies it without passlib.
ERP_HASH = "$pbkdf2-sha256$29000$LuX8f895T2kNYcx5T2nt3Q$D5HIS3SGDVbL0W7HeOWXMlT9lQuv4dWlA8wOFbs0AW8"


def _store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _lokal(store: ConsoleStore, email: str = EMAIL, sandi: str = SANDI, nama: str = NAMA) -> str:
    store.upsert_operator_lokal(
        {"email": email, "nama": nama, "password_hash": hash_password(sandi)}
    )
    return operator_id_for(email)


def _erp(store: ConsoleStore, email: str = EMAIL, *, nama: str = NAMA, active: int = 1) -> str:
    store.upsert_operator_erp(
        {
            "email": email,
            "nama": nama,
            "password_hash": ERP_HASH,
            "erp_name": email,
            "active": active,
        }
    )
    return operator_id_for(email)


def test_a_local_operator_is_stored_with_a_verifiable_password(tmp_path):
    store = _store(tmp_path)
    operator_id = _lokal(store)

    row = store.operator(operator_id)

    assert (row["email"], row["nama"], row["status"]) == (EMAIL, NAMA, "active")
    assert (row["asal"], row["erp_name"]) == ("lokal", None)
    assert row["password_hash"] != SANDI


def test_an_operator_pulled_from_autoerp_keeps_the_hash_autoerp_wrote(tmp_path):
    """The pull carries the hash itself, which is the whole reason offline sign-in
    works: nothing is asked of AutoERP at login time."""
    store = _store(tmp_path)
    operator_id = _erp(store)

    row = store.operator(operator_id)

    assert (row["asal"], row["erp_name"]) == ("erp", EMAIL)
    assert row["password_hash"] == ERP_HASH


def test_the_email_is_the_account_however_it_was_typed(tmp_path):
    """Same trick as trucks (§4.B): both sides derive the id from the same normalised
    key, so an ERP row lands on the row already typed locally instead of beside it."""
    store = _store(tmp_path)

    first = _lokal(store, email="  Budi@PKS.test ")
    second = operator_id_for(EMAIL)

    assert first == second
    assert store.operator(second)["email"] == EMAIL
    assert len(store.operators()) == 1


def test_a_pull_never_overwrites_a_local_account(tmp_path):
    """The support account exists so a mill with no internet can be opened. A pull that
    replaces its password takes that away exactly when it is needed."""
    store = _store(tmp_path)
    operator_id = _lokal(store)
    before = store.operator(operator_id)["password_hash"]

    _erp(store)

    row = store.operator(operator_id)
    assert row["password_hash"] == before
    assert (row["asal"], row["erp_name"]) == ("lokal", None)


def test_the_console_never_overwrites_an_account_autoerp_owns(tmp_path):
    """AutoERP owns its accounts; a password changed on this PC would be silently undone
    by the next pull anyway, so the write is refused rather than half-applied."""
    store = _store(tmp_path)
    operator_id = _erp(store)

    _lokal(store)

    row = store.operator(operator_id)
    assert row["password_hash"] == ERP_HASH
    assert row["asal"] == "erp"


def test_a_later_pull_does_update_the_password_autoerp_changed(tmp_path):
    """Backoffice resetting a password has to reach the mill — that is the point of the
    pull. Only the previous rule (local rows) is exempt."""
    store = _store(tmp_path)
    operator_id = _erp(store)
    baru = "$pbkdf2-sha256$29000$GgPAeE9pTSnlHMOYc25NqQ$xm8TMCM65o6kxwljP.UukzwU7RMx9CUur3dwsgfNoAQ"

    store.upsert_operator_erp(
        {"email": EMAIL, "nama": NAMA, "password_hash": baru, "erp_name": EMAIL, "active": 1}
    )

    assert store.operator(operator_id)["password_hash"] == baru


def test_an_operator_deactivated_in_autoerp_is_switched_off_here(tmp_path):
    """`active = 0` in the DocType is how backoffice removes someone who left. It has to
    take their name off this screen too, not merely stop the next pull."""
    store = _store(tmp_path)
    operator_id = _erp(store)

    _erp(store, active=0)

    assert store.operator(operator_id)["status"] == "off"
    assert store.operators() == []


def test_a_pull_that_deactivates_someone_ends_the_sessions_they_hold(tmp_path):
    """Someone dismissed in the morning must not still be signed in at the mill all
    afternoon on a token minted before the pull."""
    store = _store(tmp_path)
    operator_id = _erp(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    _erp(store, active=0)

    assert store.session(token, now=1000.0) is None


def test_resetting_a_local_password_replaces_it_and_keeps_one_row(tmp_path):
    store = _store(tmp_path)
    _lokal(store)
    before = store.operator(operator_id_for(EMAIL))["password_hash"]

    _lokal(store, sandi="sawit2027")

    assert [row["email"] for row in store.operators()] == [EMAIL]
    assert store.operator(operator_id_for(EMAIL))["password_hash"] != before


def test_the_sign_in_screen_lists_accounts_without_their_hashes(tmp_path):
    """`operators()` feeds the screen before anyone is signed in, so an unauthenticated
    page can read whatever it returns."""
    store = _store(tmp_path)
    _lokal(store)

    listing = store.operators()

    assert all("password_hash" not in row for row in listing)
    assert [row["email"] for row in listing] == [EMAIL]


def test_an_operator_switched_off_is_gone_from_the_sign_in_screen(tmp_path):
    store = _store(tmp_path)
    operator_id = _lokal(store)

    store.set_operator_status(operator_id, "off")

    assert store.operators() == []
    assert store.operator(operator_id)["status"] == "off"


def test_the_row_can_be_found_by_email_because_that_is_what_gets_typed(tmp_path):
    """Sign-in has an email, not an id. Deriving the id works only while the rule is
    identical on both sides, so the lookup is the store's job, not the caller's."""
    store = _store(tmp_path)
    _lokal(store)

    assert store.operator_by_email("  BUDI@pks.TEST ")["email"] == EMAIL
    assert store.operator_by_email("tidak@ada.test") is None


def test_wrong_passwords_are_counted_and_the_count_is_cleared_on_the_way_in(tmp_path):
    """The count is what `lockout_seconds_left` reads, so it has to survive a restart —
    an operator cannot be allowed to reset it by reloading the page."""
    store = _store(tmp_path)
    operator_id = _lokal(store)

    store.record_login_failure(operator_id, now=1000.0)
    store.record_login_failure(operator_id, now=1001.0)
    row = store.operator(operator_id)
    assert (row["gagal_count"], row["gagal_terakhir"]) == (2, 1001.0)

    store.clear_login_failures(operator_id)
    row = store.operator(operator_id)
    assert (row["gagal_count"], row["gagal_terakhir"]) == (0, None)


def test_a_session_names_the_operator_it_belongs_to(tmp_path):
    store = _store(tmp_path)
    operator_id = _lokal(store)
    token = new_session_token()

    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    session = store.session(token, now=1000.0)
    assert (session["operator_id"], session["nama"], session["email"]) == (
        operator_id,
        NAMA,
        EMAIL,
    )


def test_a_session_past_its_hour_is_no_session_at_all(tmp_path):
    store = _store(tmp_path)
    operator_id = _lokal(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=60)

    assert store.session(token, now=1059.0) is not None
    assert store.session(token, now=1061.0) is None


def test_signing_out_ends_that_session_only(tmp_path):
    store = _store(tmp_path)
    operator_id = _lokal(store)
    mine, theirs = new_session_token(), new_session_token()
    store.create_session(mine, operator_id, now=1000.0, ttl_s=60)
    store.create_session(theirs, operator_id, now=1000.0, ttl_s=60)

    store.delete_session(mine)

    assert store.session(mine, now=1000.0) is None
    assert store.session(theirs, now=1000.0) is not None


def test_an_unknown_token_is_not_a_session(tmp_path):
    assert _store(tmp_path).session("tidak-pernah-ada", now=1000.0) is None


def test_expired_sessions_can_be_swept_so_the_table_stays_small(tmp_path):
    store = _store(tmp_path)
    operator_id = _lokal(store)
    old, fresh = new_session_token(), new_session_token()
    store.create_session(old, operator_id, now=1000.0, ttl_s=60)
    store.create_session(fresh, operator_id, now=1000.0, ttl_s=43200)

    assert store.purge_sessions(now=2000.0) == 1
    assert store.session(fresh, now=2000.0) is not None


def test_resetting_a_password_ends_every_session_opened_with_the_old_one(tmp_path):
    """A password is reset because someone saw it. A session opened with it that keeps
    working for another twelve hours makes the reset a formality."""
    store = _store(tmp_path)
    operator_id = _lokal(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    _lokal(store, sandi="sawit2027")

    assert store.session(token, now=1000.0) is None


def test_switching_an_operator_back_on_does_not_revive_the_sessions_they_held(tmp_path):
    """Filtering on status alone would hand an old, unexpired token its power back the
    moment the account is reactivated."""
    store = _store(tmp_path)
    operator_id = _lokal(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    store.set_operator_status(operator_id, "off")
    store.set_operator_status(operator_id, "active")

    assert store.session(token, now=1000.0) is None


def test_a_session_of_an_operator_switched_off_stops_working(tmp_path):
    """Switching someone off is how a leaver is handled; a session they still hold must
    not outlive it."""
    store = _store(tmp_path)
    operator_id = _lokal(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    store.set_operator_status(operator_id, "off")

    assert store.session(token, now=1000.0) is None
