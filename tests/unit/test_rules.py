"""Unit tests for domain ripeness rules (B1).

derive_ripeness_status decides Acc vs Rej — the classification that ends up as a
grading event to palmgrade-api, so it directly affects tonnage accounting. These
tests lock the current behavior against regressions.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.rules import derive_ripeness_status


@pytest.mark.parametrize("label", ["rej", "REJ", "Rej", "unripe_rej", "rejected"])
def test_label_containing_rej_is_rej(label):
    assert derive_ripeness_status(label) == "rej"


@pytest.mark.parametrize("label", ["acc", "ACC", "ripe", "tp", "accepted"])
def test_label_without_rej_is_acc(label):
    assert derive_ripeness_status(label) == "acc"


def test_area_below_minimum_forces_rej_even_for_acc_label():
    # Too small to be a valid fruit → rej regardless of the model label.
    assert derive_ripeness_status("acc", area=100, minimum_size=460000) == "rej"


def test_area_at_or_above_minimum_keeps_acc():
    assert derive_ripeness_status("acc", area=460000, minimum_size=460000) == "acc"
    assert derive_ripeness_status("acc", area=500000, minimum_size=460000) == "acc"


def test_minimum_size_disabled_when_zero():
    # minimum_size=0 (default) → size check skipped entirely.
    assert derive_ripeness_status("acc", area=1, minimum_size=0) == "acc"


def test_area_zero_skips_size_check():
    # area=0 means "unknown/unmeasured" → do not force rej on size.
    assert derive_ripeness_status("acc", area=0, minimum_size=460000) == "acc"


def test_rej_label_stays_rej_regardless_of_size():
    assert derive_ripeness_status("rej", area=500000, minimum_size=460000) == "rej"
