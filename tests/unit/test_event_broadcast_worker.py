import asyncio
import json

from palmgrade.workers.event_broadcast_worker import EventBroadcastWorker
from palmgrade.workers.runtime_state import RuntimeState


class _FakeClient:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    async def send_text(self, data: str) -> None:
        if self.fail:
            raise RuntimeError("client gone")
        self.sent.append(data)


def _drive(worker: EventBroadcastWorker) -> None:
    """Jalankan run_loop cukup lama untuk memproses queue lalu batalkan.

    Pakai asyncio.run langsung (stdlib) — tidak butuh pytest-asyncio, jadi aman
    di CI yang hanya install `ruff pytest`.
    """

    async def _runner() -> None:
        task = asyncio.create_task(worker.run_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_runner())


def test_broadcasts_queued_event_to_clients():
    state = RuntimeState()
    client = _FakeClient()
    state.websocket_clients.append(client)
    state.event_queue.put({"type": "inspection_saved", "id": 1})

    _drive(EventBroadcastWorker(state=state, poll_timeout=0.01))

    assert client.sent == [json.dumps({"type": "inspection_saved", "id": 1})]


def test_dead_client_removed_on_send_failure():
    state = RuntimeState()
    dead = _FakeClient(fail=True)
    state.websocket_clients.append(dead)
    state.event_queue.put({"type": "x"})

    _drive(EventBroadcastWorker(state=state, poll_timeout=0.01))

    assert dead not in state.websocket_clients


def test_idle_does_not_raise_when_queue_empty():
    state = RuntimeState()
    # tidak ada event — loop harus idle tanpa error
    _drive(EventBroadcastWorker(state=state, poll_timeout=0.01))
    assert state.websocket_clients == []
