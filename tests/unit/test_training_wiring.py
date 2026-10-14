"""Training photos are wired only when configured, and shown to support.

The Danger Zone wipe of the training queue is tested in `test_bahaya_service.py` (its
`rakit` fixture), the Status route in `test_dev_routes.py`.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from palmgrade.core.config import Settings
from palmgrade.integrations.upload.r2_uploader import KIRIM_CONFIG
from palmgrade.integrations.upload.training_outbox_store import TrainingOutboxStore
from palmgrade.repositories.log_repository import LogStore
from palmgrade.services.dev_service import DevService

ENDPOINT = "http://127.0.0.1:9000"


def _settings(tmp_path, **training):
    """`state/` in a temp folder: the real composition root would open the developer's
    `state/console.db`. Every training field starts empty so the host env cannot leak in."""
    kosong = {
        "training_inbox_bucket": "",
        "training_inbox_endpoint": "",
        "training_inbox_access_key_id": "",
        "training_inbox_secret_access_key": "",
    }
    return replace(
        Settings(), repo_root=tmp_path, factory_tz="Asia/Jakarta", erp_url="", r2_bucket="",
        r2_account_id="", **{**kosong, **training},
    )


def _rakit(monkeypatch, settings):
    from palmgrade.routes import console_deps

    monkeypatch.setattr(console_deps, "Settings", lambda: settings)
    console_deps.get_console_service.cache_clear()
    try:
        return console_deps.get_console_service()
    finally:
        console_deps.get_console_service.cache_clear()


def test_dev_card_says_off_when_not_configured(tmp_path):
    dev = DevService(LogStore(tmp_path / "log.db", retention_days=7))
    assert dev.training_queue() == {"aktif": False}


def test_dev_card_counts_and_last_sent(tmp_path):
    clock = [5000.0]
    outbox = TrainingOutboxStore(tmp_path / "t.db", clock=lambda: clock[0])
    outbox.enqueue("e-1", "line-1", "/p/1.webp", {})
    outbox.enqueue("e-2", "line-1", "/p/2.webp", {})
    outbox.mark_sent("e-1")
    dev = DevService(LogStore(tmp_path / "log.db", retention_days=7), training_outbox=outbox)
    got = dev.training_queue()
    assert got["aktif"] is True and got["pending"] == 1 and got["gagal"] == 0
    assert got["terakhir_terkirim"] == 5000.0 and got["items"] == []


def test_console_service_has_no_inbox_without_bucket(monkeypatch, tmp_path, caplog):
    uji = _settings(tmp_path)
    with caplog.at_level(logging.INFO, logger="palmgrade.routes.console_deps"):
        svc = _rakit(monkeypatch, uji)
    assert svc.training_inbox is None and svc.training_worker is None
    # Off switch: no outbox file is created (global constraint).
    assert not uji.training_outbox_db_path.exists()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING and "Training" in r.getMessage()]


def test_console_service_wires_inbox_with_bucket(monkeypatch, tmp_path):
    uji = _settings(
        tmp_path, training_inbox_bucket="nexio-inbox", training_inbox_endpoint=ENDPOINT,
        training_inbox_access_key_id="k", training_inbox_secret_access_key="s",
    )
    svc = _rakit(monkeypatch, uji)
    assert svc.training_inbox is not None
    assert svc.training_worker is not None and svc.training_worker.outbox is svc.training_inbox.outbox
    assert uji.training_outbox_db_path.exists()


def test_training_uploader_has_its_endpoint_and_timeouts(monkeypatch, tmp_path):
    """B4: every upload has a timeout; with config None boto's defaults would apply."""
    uji = _settings(
        tmp_path, training_inbox_bucket="nexio-inbox", training_inbox_endpoint=ENDPOINT,
        training_inbox_access_key_id="k", training_inbox_secret_access_key="s",
    )
    uploader = _rakit(monkeypatch, uji).training_worker._uploader
    assert uploader._config is KIRIM_CONFIG
    assert uploader._endpoint_url == ENDPOINT and uploader.bucket == "nexio-inbox"


def test_bucket_without_keys_stays_off_with_one_warning(monkeypatch, tmp_path, caplog):
    """D8: a half-filled `.env` must not start a worker that fails every minute."""
    uji = _settings(tmp_path, training_inbox_bucket="nexio-inbox", training_inbox_endpoint=ENDPOINT)
    with caplog.at_level(logging.INFO, logger="palmgrade.routes.console_deps"):
        svc = _rakit(monkeypatch, uji)
    assert svc.training_inbox is None and svc.training_worker is None
    assert not uji.training_outbox_db_path.exists()
    peringatan = [r for r in caplog.records if r.levelno == logging.WARNING and "Training" in r.getMessage()]
    assert len(peringatan) == 1


def test_unknown_app_version_goes_out_as_null(monkeypatch, tmp_path):
    """D9: the Dockerfile default `unknown` is not a version; the manifest says null."""
    uji = replace(
        _settings(
            tmp_path, training_inbox_bucket="nexio-inbox", training_inbox_endpoint=ENDPOINT,
            training_inbox_access_key_id="k", training_inbox_secret_access_key="s",
        ),
        app_version="unknown",
    )
    svc = _rakit(monkeypatch, uji)
    assert svc.training_inbox._autograde_version == ""


def test_a_corrupt_outbox_file_does_not_stop_the_console(monkeypatch, tmp_path, caplog):
    """Final review M4: a damaged training_outbox.db turns the feature off, the console boots."""
    uji = _settings(
        tmp_path, training_inbox_bucket="nexio-inbox", training_inbox_endpoint=ENDPOINT,
        training_inbox_access_key_id="k", training_inbox_secret_access_key="s",
    )
    uji.training_outbox_db_path.parent.mkdir(parents=True, exist_ok=True)
    uji.training_outbox_db_path.write_bytes(b"this is not a sqlite file" * 100)
    with caplog.at_level(logging.INFO, logger="palmgrade.routes.console_deps"):
        svc = _rakit(monkeypatch, uji)
    assert svc.training_inbox is None and svc.training_worker is None
    assert len([r for r in caplog.records if r.levelno == logging.ERROR and "Training" in r.getMessage()]) == 1
