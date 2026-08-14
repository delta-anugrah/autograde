import pytest

from palmgrade.plc.pulse import PulseScheduler


def _sched(pulse=0.2, gap=0.1, queue_max=20):
    return PulseScheduler(pulse_s=pulse, gap_s=gap, queue_max=queue_max)


def test_gap_must_be_positive():
    # gap 0 membuat OFF dan ON jatuh pada tick yang sama -> PLC tak pernah
    # melihat tepi turun. Dilarang di konstruktor, bukan ditemukan di pabrik.
    with pytest.raises(ValueError):
        PulseScheduler(pulse_s=0.2, gap_s=0.0, queue_max=20)


def test_single_pulse_turns_on_then_off():
    s = _sched()
    assert s.enqueue(4) is True
    assert s.tick(now=0.0) == {4: True}
    assert s.tick(now=0.1) == {}          # masih di tengah pulse
    assert s.tick(now=0.2) == {4: False}  # tepat di ujung pulse


def test_two_pulses_same_coil_do_not_merge():
    s = _sched()
    s.enqueue(4)
    s.enqueue(4)
    assert s.tick(now=0.0) == {4: True}
    assert s.tick(now=0.2) == {4: False}   # pulse pertama selesai
    assert s.tick(now=0.25) == {}          # masih di dalam gap
    assert s.tick(now=0.3) == {4: True}    # pulse kedua baru mulai
    assert s.tick(now=0.5) == {4: False}


def test_different_coils_are_independent():
    s = _sched()
    s.enqueue(0)
    s.enqueue(1)
    assert s.tick(now=0.0) == {0: True, 1: True}


def test_overflow_drops_and_counts():
    s = _sched(queue_max=2)
    assert s.enqueue(0) is True
    assert s.enqueue(0) is True
    assert s.enqueue(0) is False
    assert s.dropped == 1


def test_idle_scheduler_reports_no_changes():
    assert _sched().tick(now=1.0) == {}
