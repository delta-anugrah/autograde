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


def konfigurasi(app, *, lifespan: str = "off") -> uvicorn.Config:
    """`uvicorn.Config` seperti `entrypoint.sh`, dengan h11 menggantikan httptools.

    Produksi memasang `uvicorn[standard]`, jadi yang jalan di sana `httptools`; di CI
    cuma ada h11. Baris access log dan "Exception in ASGI application" keduanya
    ditulis dengan logger, format, dan argumen yang sama, jadi yang dibuktikan di sini
    berlaku untuk keduanya. Tanpa websocket (`ws="none"`): tidak ada yang diuji lewat
    sana, dan memuat protokolnya cuma memunculkan DeprecationWarning pustaka
    `websockets`.

    Membuatnya memasang konfigurasi log bawaan uvicorn, persis urutan boot: uvicorn
    dulu, baru lifespan app yang memasang `configure_logging`. Bawaannya tanpa
    lifespan uvicorn (test menjalankan lifespan app sendiri); `lifespan="on"` untuk
    menjalankannya lewat `uvicorn.lifespan.on.LifespanOn`, seperti saat boot.
    """
    config = uvicorn.Config(app, http="h11", ws="none", lifespan=lifespan)
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
    keluar = bytes(transport.keluar)
    assert keluar, f"uvicorn tidak menjawab {metode} {jalur} dalam 5 detik"
    return int(keluar.split(b" ", 2)[1])
