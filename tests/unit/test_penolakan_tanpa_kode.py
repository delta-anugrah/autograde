"""Operator refusals without a code: generic on screen, their own text in the Log tab."""
from __future__ import annotations

import logging

from palmgrade.domain.operator_error import OperatorError
from palmgrade.routes.console_deps import _operator_error


def test_penolakan_tanpa_kode_tercatat_di_tab_log(caplog):
    """A refusal with no operator code reaches the screen as the generic sentence, which
    points to the Log tab (2026-10-01); so its own text must be logged there."""
    with caplog.at_level(logging.WARNING, logger="palmgrade.routes.console_deps"):
        jawab = _operator_error(400, ValueError("conf_threshold harus antara 0 dan 1"))
        _operator_error(400, OperatorError("plat_kosong", "plat kosong"))

    assert jawab.detail == "conf_threshold harus antara 0 dan 1"
    pesan = [r.getMessage() for r in caplog.records]
    assert len(pesan) == 1 and "conf_threshold harus antara 0 dan 1" in pesan[0], pesan
