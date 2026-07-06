"""Unit tests for StreamingService.generate_frames MJPEG keep-alive (B2).

Regression guard for the threadpool-starvation bug: when the camera is down and
no new frame arrives, the generator must still yield periodically so the WSGI/
anyio thread notices client disconnect and returns to the pool. Before the fix
it blocked forever without yielding, leaking one thread per reconnect attempt.
"""
from __future__ import annotations

import itertools

from palmgrade.services.streaming_service import StreamingService
from palmgrade.workers.runtime_state import RuntimeState

KEEPALIVE = b"--frame\r\n\r\n"


def _take(gen, n):
    return list(itertools.islice(gen, n))


def _service(state):
    # idle_yield_after=1 → keep-alive tiap idle tick; wait_timeout=0 → tidak ada
    # sleep nyata, test deterministik & instan (tidak bergantung threading).
    return StreamingService(state, idle_yield_after=1, wait_timeout=0)


def test_yields_frame_when_available():
    state = RuntimeState()
    state.latest_frame = b"JPEGDATA"
    svc = _service(state)

    out = _take(svc.generate_frames(), 1)

    assert len(out) == 1
    assert b"JPEGDATA" in out[0]
    assert out[0].startswith(b"--frame\r\n")
    assert b"Content-Type: image/jpeg" in out[0]


def test_emits_keepalive_when_no_frame_ever_arrives():
    # Camera down: latest_frame stays None. Generator must emit keep-alive
    # boundaries instead of blocking forever, so disconnect can be detected.
    state = RuntimeState()  # latest_frame is None
    svc = _service(state)

    out = _take(svc.generate_frames(), 3)

    assert len(out) == 3
    assert all(chunk == KEEPALIVE for chunk in out)


def test_does_not_resend_same_frame_but_keeps_alive():
    # A single stale frame must be sent once; subsequent idle ticks are
    # keep-alives, never a duplicate of the same frame object.
    state = RuntimeState()
    state.latest_frame = b"STALEFRAME"
    svc = _service(state)

    out = _take(svc.generate_frames(), 3)

    real = [c for c in out if b"STALEFRAME" in c]
    keepalive = [c for c in out if c == KEEPALIVE]
    assert len(real) == 1
    assert len(keepalive) == 2


def test_new_frame_after_idle_is_sent():
    state = RuntimeState()
    svc = _service(state)
    gen = svc.generate_frames()

    # Two idle ticks first (no frame) → keep-alives.
    first_two = _take(gen, 2)
    assert all(c == KEEPALIVE for c in first_two)

    # Frame arrives; next tick must deliver it.
    state.latest_frame = b"FRESH"
    nxt = _take(gen, 1)
    assert b"FRESH" in nxt[0]
