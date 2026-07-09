from __future__ import annotations

import asyncio
import json
import queue

from .runtime_state import RuntimeState


class EventBroadcastWorker:
    def __init__(self, state: RuntimeState, poll_timeout: float = 1.0) -> None:
        self.state = state
        # Blocking get dengan timeout → thread parkir di condition variable queue
        # (tanpa CPU busy-poll). Timeout kecil supaya loop tetap responsif ke cancel.
        self._poll_timeout = poll_timeout

    async def run_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                event = await loop.run_in_executor(None, self._blocking_get)
            except asyncio.CancelledError:
                raise
            if event is None:
                continue
            data = json.dumps(event)
            for client in self.state.websocket_clients[:]:
                try:
                    await client.send_text(data)
                except Exception:
                    self.state.websocket_clients.remove(client)

    def _blocking_get(self):
        """Ambil 1 event; kembalikan None kalau idle (timeout) supaya loop bisa cek cancel."""
        try:
            return self.state.event_queue.get(timeout=self._poll_timeout)
        except queue.Empty:
            return None
