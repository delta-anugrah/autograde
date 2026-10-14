"""TRAINING_INBOX_* settings: empty means off, a typo means the default and a WARNING, never a dead boot."""

from __future__ import annotations

import logging

import pytest

from palmgrade.core.config import Settings
from palmgrade.domain.training_sample import SEND_MODES


def test_off_by_default(monkeypatch):
    for name in ("TRAINING_INBOX_BUCKET", "TRAINING_INBOX_ENDPOINT", "R2_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    s = Settings()
    assert s.training_inbox_bucket == ""
    assert s.training_inbox_endpoint_url == ""
    assert s.training_inbox_send == "all"
    assert s.training_inbox_low_confidence == pytest.approx(0.60)


def test_endpoint_defaults_to_the_r2_account(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "abc123")
    monkeypatch.delenv("TRAINING_INBOX_ENDPOINT", raising=False)
    assert Settings().training_inbox_endpoint_url == "https://abc123.r2.cloudflarestorage.com"


def test_explicit_endpoint_wins(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "abc123")
    monkeypatch.setenv("TRAINING_INBOX_ENDPOINT", "http://127.0.0.1:9000/")
    assert Settings().training_inbox_endpoint_url == "http://127.0.0.1:9000"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("priority", "priority"), (" ALL ", "all"), ("semua", "all"), ("", "all"), ("  ", "all")],
)
def test_send_mode(monkeypatch, caplog, raw, expected):
    monkeypatch.setenv("TRAINING_INBOX_SEND", raw)
    with caplog.at_level(logging.WARNING):
        assert Settings().training_inbox_send == expected
    assert ("TRAINING_INBOX_SEND" in caplog.text) == (raw == "semua")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0.5", 0.5), ("abc", 0.60), ("1.5", 0.60), ("-0.1", 0.60), ("", 0.60), ("  ", 0.60)],
)
def test_low_confidence(monkeypatch, caplog, raw, expected):
    monkeypatch.setenv("TRAINING_INBOX_LOW_CONFIDENCE", raw)
    with caplog.at_level(logging.WARNING):
        assert Settings().training_inbox_low_confidence == pytest.approx(expected)
    mistyped = raw.strip() in {"abc", "1.5", "-0.1"}
    assert ("TRAINING_INBOX_LOW_CONFIDENCE" in caplog.text) == mistyped


def test_send_modes_match_the_domain():
    from palmgrade.core import config

    assert config._TRAINING_SEND_MODES == SEND_MODES


def test_outbox_file_lives_in_state_dir():
    s = Settings()
    assert s.training_outbox_db_path == s.state_dir / "training_outbox.db"
