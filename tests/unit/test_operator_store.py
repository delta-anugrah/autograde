"""Operator accounts and their sessions in the console index (Fase 4, plan §6.5).

Local accounts, decided 2026-09-15: AutoERP has no operator DocType, and the password
hashes Frappe does hold live in `__Auth`, which it deliberately never serves over REST.
The console must also let an operator in while the internet is down. `erp_name` is
already on the row so that the day AutoERP grows that DocType, these rows have
somewhere to point.
"""

from __future__ import annotations

from palmgrade.domain.operator_auth import hash_pin, new_session_token, operator_id_for
from palmgrade.repositories.console_repository import ConsoleStore

NAMA = "Pak Budi"
PIN = "142536"


def _store(tmp_path) -> ConsoleStore:
    return ConsoleStore(tmp_path / "console.db")


def _operator(store: ConsoleStore, nama: str = NAMA, pin: str = PIN) -> str:
    store.upsert_operator({"nama": nama, "pin_hash": hash_pin(pin)})
    return operator_id_for(nama)


def test_an_operator_is_stored_with_a_verifiable_pin(tmp_path):
    store = _store(tmp_path)
    operator_id = _operator(store)

    row = store.operator(operator_id)

    assert (row["nama"], row["status"], row["erp_name"]) == (NAMA, "active", None)
    assert row["pin_hash"] != PIN


def test_adding_the_same_operator_again_replaces_the_pin_and_keeps_one_row(tmp_path):
    """Re-running the operator command is how a forgotten PIN is reset."""
    store = _store(tmp_path)
    _operator(store)

    _operator(store, pin="908171")

    rows = store.operators()
    assert [row["nama"] for row in rows] == [NAMA]
    assert store.operator(operator_id_for(NAMA))["pin_hash"] != hash_pin(PIN)


def test_the_keypad_listing_never_carries_the_hashes(tmp_path):
    """`operators()` feeds the screen before anyone is logged in. A hash must not be
    part of what an unauthenticated page can read."""
    store = _store(tmp_path)
    _operator(store)

    assert all("pin_hash" not in row for row in store.operators())


def test_an_operator_switched_off_is_gone_from_the_keypad(tmp_path):
    store = _store(tmp_path)
    operator_id = _operator(store)

    store.set_operator_status(operator_id, "off")

    assert store.operators() == []
    assert store.operator(operator_id)["status"] == "off"


def test_wrong_pins_are_counted_and_the_count_is_cleared_on_the_way_in(tmp_path):
    """The count is what `lockout_seconds_left` reads, so it has to survive a restart —
    an operator cannot be allowed to reset it by reloading the page."""
    store = _store(tmp_path)
    operator_id = _operator(store)

    store.record_login_failure(operator_id, now=1000.0)
    store.record_login_failure(operator_id, now=1001.0)
    row = store.operator(operator_id)
    assert (row["gagal_count"], row["gagal_terakhir"]) == (2, 1001.0)

    store.clear_login_failures(operator_id)
    row = store.operator(operator_id)
    assert (row["gagal_count"], row["gagal_terakhir"]) == (0, None)


def test_a_session_names_the_operator_it_belongs_to(tmp_path):
    store = _store(tmp_path)
    operator_id = _operator(store)
    token = new_session_token()

    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    session = store.session(token, now=1000.0)
    assert (session["operator_id"], session["nama"]) == (operator_id, NAMA)


def test_a_session_past_its_hour_is_no_session_at_all(tmp_path):
    store = _store(tmp_path)
    operator_id = _operator(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=60)

    assert store.session(token, now=1059.0) is not None
    assert store.session(token, now=1061.0) is None


def test_signing_out_ends_that_session_only(tmp_path):
    store = _store(tmp_path)
    operator_id = _operator(store)
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
    operator_id = _operator(store)
    old, fresh = new_session_token(), new_session_token()
    store.create_session(old, operator_id, now=1000.0, ttl_s=60)
    store.create_session(fresh, operator_id, now=1000.0, ttl_s=43200)

    assert store.purge_sessions(now=2000.0) == 1
    assert store.session(fresh, now=2000.0) is not None


def test_resetting_a_pin_ends_every_session_opened_with_the_old_one(tmp_path):
    """A PIN is reset because the shift saw it. A session opened with it that keeps
    working for another twelve hours makes the reset a formality."""
    store = _store(tmp_path)
    operator_id = _operator(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    _operator(store, pin="908171")

    assert store.session(token, now=1000.0) is None


def test_switching_an_operator_back_on_does_not_revive_the_sessions_they_held(tmp_path):
    """Filtering on status alone would hand an old, unexpired token its power back the
    moment the account is reactivated."""
    store = _store(tmp_path)
    operator_id = _operator(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    store.set_operator_status(operator_id, "off")
    store.set_operator_status(operator_id, "active")

    assert store.session(token, now=1000.0) is None


def test_a_session_of_an_operator_switched_off_stops_working(tmp_path):
    """Switching someone off is how a lost PIN or a leaver is handled; a session they
    still hold must not outlive it."""
    store = _store(tmp_path)
    operator_id = _operator(store)
    token = new_session_token()
    store.create_session(token, operator_id, now=1000.0, ttl_s=43200)

    store.set_operator_status(operator_id, "off")

    assert store.session(token, now=1000.0) is None
