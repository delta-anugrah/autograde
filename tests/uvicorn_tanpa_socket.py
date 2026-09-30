"""Satu permintaan HTTP lewat protokol uvicorn yang SUNGGUHAN, tanpa socket dan server.

Dipakai test logging batch 3: access log dan "Exception in ASGI application" ditulis
oleh protokol uvicorn, bukan oleh app. `TestClient`/`httpx.ASGITransport` melewatinya
sama sekali, jadi keduanya tidak bisa membuktikan baris itu sampai ke mana. Di sini
`H11Protocol` asli diberi byte permintaan dan transport palsu yang menampung jawaban.
"""
from __future__ import annotations

import asyncio

import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.server import ServerState


class _Transport(asyncio.Transport):
    def __init__(self) -> None:
        super().__init__()
        self.keluar = bytearray()
        self._tutup = False

    def get_extra_info(self, name, default=None):
        return {"peername": ("127.0.0.1", 50000), "sockname": ("127.0.0.1", 8100)}.get(name, default)

    def write(self, data) -> None:
        self.keluar.extend(data)

    def close(self) -> None:
        self._tutup = True

    def is_closing(self) -> bool:
        return self._tutup

    def pause_reading(self) -> None:
        pass

    def resume_reading(self) -> None:
        pass


def konfigurasi(app) -> uvicorn.Config:
    """`uvicorn.Config` seperti `entrypoint.sh` (h11, tanpa lifespan uvicorn).

    Membuatnya memasang konfigurasi log bawaan uvicorn, persis urutan boot: uvicorn
    dulu, baru lifespan app yang memasang `configure_logging`.
    """
    config = uvicorn.Config(app, http="h11", lifespan="off")
    config.load()
    return config


async def minta(config: uvicorn.Config, jalur: str, *, metode: str = "GET", header: dict | None = None) -> int:
    """Kirim satu permintaan, tunggu jawabannya selesai, kembalikan kode status HTTP."""
    transport = _Transport()
    protokol = H11Protocol(config=config, server_state=ServerState(), app_state={})
    protokol.connection_made(transport)
    baris = [f"{metode} {jalur} HTTP/1.1", "Host: localhost", "Connection: close"]
    baris += [f"{k}: {v}" for k, v in (header or {}).items()]
    protokol.data_received(("\r\n".join(baris) + "\r\n\r\n").encode())
    for _ in range(500):
        if transport.is_closing():
            break
        await asyncio.sleep(0.01)
    return int(bytes(transport.keluar).split(b" ", 2)[1])
