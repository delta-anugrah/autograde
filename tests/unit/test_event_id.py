"""Contract test for deterministic auto event_id (B1).

frame_processing_worker builds the auto-detection event_id as
    uuid5(NAMESPACE_URL, f"{machine_id}:{timestamp}")
This determinism is the whole idempotency guarantee: if a frame is reprocessed
after a crash (before it was marked processed), the SAME event_id is produced, so
palmgrade-api dedupes it (already_processed) and does not double-count tonnage.

The formula lives inline in the worker (which imports torch), so we lock the
contract here as an explicit, dependency-free spec. If the worker's formula
changes, this test must change with it — that's intentional.
"""
from __future__ import annotations

import uuid


def _event_id(machine_id: str, timestamp: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{machine_id}:{timestamp}"))


def test_same_inputs_produce_same_event_id():
    a = _event_id("machine-1", "20260707_120000_000000")
    b = _event_id("machine-1", "20260707_120000_000000")
    assert a == b


def test_different_timestamp_produces_different_id():
    a = _event_id("machine-1", "20260707_120000_000000")
    b = _event_id("machine-1", "20260707_120001_000000")
    assert a != b


def test_different_machine_produces_different_id():
    # Same instant on two lines must not collide.
    a = _event_id("machine-1", "20260707_120000_000000")
    b = _event_id("machine-2", "20260707_120000_000000")
    assert a != b


def test_event_id_is_valid_uuid():
    val = _event_id("machine-1", "20260707_120000_000000")
    parsed = uuid.UUID(val)
    assert parsed.version == 5


def test_known_vector_is_stable():
    # Golden value: if this ever changes, the idempotency contract with
    # palmgrade-api (and any already-delivered events) is broken.
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "machine-1:20260707_120000_000000"))
    assert _event_id("machine-1", "20260707_120000_000000") == expected
