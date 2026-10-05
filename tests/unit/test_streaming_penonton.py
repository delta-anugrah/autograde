"""`StreamingService` counts who is watching the MJPEG stream (batch 6.3).

`DisplayWorker` reads that count and stops rendering when it is zero. A viewer that is never
counted out would keep a line rendering for nobody; one counted out twice would freeze the
picture for somebody who is still watching.
"""
from __future__ import annotations

import pytest

from palmgrade.services.streaming_service import StreamingService
from palmgrade.workers.runtime_state import RuntimeState


def _service(state: RuntimeState) -> StreamingService:
    return StreamingService(state, idle_yield_after=1, wait_timeout=0)


def test_belum_ada_yang_menonton_sebelum_stream_dibaca():
    state = RuntimeState()
    stream = _service(state).generate_frames()

    assert state.penonton_stream == 0, "an unread stream is not a viewer"
    stream.close()
    assert state.penonton_stream == 0


def test_penonton_dihitung_selama_membaca_dan_dikurangi_saat_pergi():
    state = RuntimeState()
    stream = _service(state).generate_frames()

    next(stream)
    assert state.penonton_stream == 1
    next(stream)
    assert state.penonton_stream == 1, "one viewer was counted twice"

    stream.close()  # the browser closed the connection
    assert state.penonton_stream == 0


def test_dua_penonton_dihitung_sendiri_sendiri():
    state = RuntimeState()
    service = _service(state)
    satu, dua = service.generate_frames(), service.generate_frames()
    next(satu)
    next(dua)

    assert state.penonton_stream == 2
    satu.close()
    assert state.penonton_stream == 1
    dua.close()
    assert state.penonton_stream == 0


def test_stream_yang_berakhir_karena_galat_tetap_dikurangi():
    class StateRusak(RuntimeState):
        @property
        def frame_condition(self):
            raise RuntimeError("boom")

        @frame_condition.setter
        def frame_condition(self, _nilai):
            pass

    state = StateRusak()
    stream = _service(state).generate_frames()

    with pytest.raises(StopIteration):
        next(stream)

    assert state.penonton_stream == 0


def test_hitungan_tidak_pernah_di_bawah_nol():
    state = RuntimeState()

    state.penonton_keluar()

    assert state.penonton_stream == 0
