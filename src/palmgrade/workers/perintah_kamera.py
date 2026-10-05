"""Commands for the camera from a request thread, run by the capture thread (rule 3).

The SDK is not safe across threads, so a route never calls it: it queues a function here and waits.
`FrameCaptureWorker.run_once` runs whatever is waiting, under `state.lock`, between two grabs. Phase 1 queues
reads only; phase 2 (apply, save) uses the same queue, which is why a command the requester gave up on is
skipped instead of run late.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, TypeVar

T = TypeVar("T")

#: How long a request waits for the capture thread. One grab is 50 ms at 20 fps; 2 s covers a slow turn and
#: still answers before the console's own 5 s timeout. A camera in a reconnect backoff answers "not now".
BATAS_PERINTAH_KAMERA_DETIK = 2.0


class KameraTidakMenjawab(RuntimeError):
    """The capture thread did not run the command in time (camera disconnected or reconnecting)."""


class AntreanPerintahKamera:
    def __init__(self) -> None:
        self._antrean: queue.Queue[tuple[Callable[[], Any], Future]] = queue.Queue()

    def minta(self, fungsi: Callable[[], T], *, batas_detik: float = BATAS_PERINTAH_KAMERA_DETIK) -> T:
        """Queue `fungsi` for the capture thread and wait for its result or its exception."""
        janji: Future = Future()
        self._antrean.put((fungsi, janji))
        try:
            return janji.result(timeout=batas_detik)
        except FutureTimeout:
            janji.cancel()  # still waiting = `jalankan` skips it; already running = its result is dropped
            raise KameraTidakMenjawab(f"capture thread did not run the camera command within {batas_detik} s") from None

    def jalankan(self, kunci: threading.Lock) -> int:
        """Run every waiting command under `kunci`. Capture thread only. Returns how many ran."""
        jumlah = 0
        while True:
            try:
                fungsi, janji = self._antrean.get_nowait()
            except queue.Empty:
                return jumlah  # nothing waiting is the normal turn
            if not janji.set_running_or_notify_cancel():
                continue  # the requester gave up: never touch the camera for it
            try:
                with kunci:
                    hasil = fungsi()
            except Exception as exc:  # handed to the requester, who logs and answers it
                janji.set_exception(exc)
            else:
                janji.set_result(hasil)
            jumlah += 1
