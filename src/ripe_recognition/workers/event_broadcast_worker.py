from __future__ import annotations

import asyncio
import json

from .runtime_state import RuntimeState


class EventBroadcastWorker:
    def __init__(self, state: RuntimeState) -> None:
        self.state = state

    async def run_loop(self) -> None:
        while True:
            if not self.state.event_queue.empty():
                data = json.dumps(self.state.event_queue.get())
                for client in self.state.websocket_clients[:]:
                    try:
                        await client.send_text(data)
                    except Exception:
                        self.state.websocket_clients.remove(client)
            await asyncio.sleep(0.05)
