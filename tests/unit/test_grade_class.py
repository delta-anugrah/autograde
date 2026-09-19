"""The four classes the new model emits, and the binary verdict they collapse to.

`best.pt` detects Ripe, Unripe, JK and TP. Two things downstream cannot take four
values and are deliberately left binary:

- the PLC owns two coils, OK and NG (`plc/worker.py`). A bunch is discarded or it
  is not; there is no third piston.
- AutoERP books `Mentah` / `Tangkai Panjang` / `Matang` (`palm_mill/api.py`
  `AI_CRITERIA`), a frozen contract.

So `grade_class` is the detail the console shows and `ripeness_status` stays the
verdict that fires pistons and is paid on. JK rides with REJ: an empty bunch is
discarded like an unripe one (decided 2026-09-16), and until AutoERP grows a
criterion for it, its count stays on the edge and is NOT sent.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.grade_class import (
    GRADE_CLASSES,
    JK,
    RIPE,
    TP,
    UNRIPE,
    grade_class_of,
    is_fruit_class,
    verdict_for_class,
)


def test_the_four_classes_are_the_vocabulary():
    assert GRADE_CLASSES == (RIPE, UNRIPE, JK, TP)


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Ripe", RIPE),
        ("ripe", RIPE),
        ("  RIPE  ", RIPE),
        ("Unripe", UNRIPE),
        ("unripe", UNRIPE),
        ("JK", JK),
        ("jk", JK),
        ("TP", TP),
        ("tp", TP),
    ],
)
def test_model_labels_normalise_whatever_their_casing(label, expected):
    """Ultralytics keeps whatever casing the training set used (the old model
    shipped `{0: 'ACC', 1: 'Rej', 2: 'TP'}` — three different styles). Matching
    on exact case is how a retrain silently stops grading."""
    assert grade_class_of(label) == expected


@pytest.mark.parametrize("label", ["", None, "acc", "rej", "banana", "matang"])
def test_a_label_outside_the_four_is_refused(label):
    """Loudly, like a malformed timestamp. A class this code does not know would
    otherwise be counted in `total` and in none of the four."""
    with pytest.raises(ValueError):
        grade_class_of(label)


@pytest.mark.parametrize(
    "grade,verdict",
    [(RIPE, "ACC"), (UNRIPE, "REJ"), (JK, "REJ")],
)
def test_fruit_classes_collapse_to_the_binary_verdict(grade, verdict):
    assert verdict_for_class(grade) == verdict


def test_jk_is_discarded_exactly_like_unripe():
    """The piston does not know what an empty bunch is; it only knows NG."""
    assert verdict_for_class(JK) == verdict_for_class(UNRIPE) == "REJ"


def test_tp_has_no_verdict_of_its_own():
    """A long stalk is a property of a bunch, not a bunch. It is carried beside
    the fruit as `tp_confidence`, never graded on its own."""
    assert verdict_for_class(TP) is None


@pytest.mark.parametrize(
    "grade,fruit", [(RIPE, True), (UNRIPE, True), (JK, True), (TP, False)]
)
def test_only_the_three_fruit_classes_are_gradeable(grade, fruit):
    assert is_fruit_class(grade) is fruit
