"""Kirim satu pesan ke webhook Discord (batch 3.5). Satu-satunya yang tahu soal HTTP-nya.

Alamat webhook itu rahasia (siapa pun yang memegangnya bisa menulis ke kanal), jadi
tidak pernah masuk log atau pesan galat: galat jaringan dilaporkan dengan nama
kelasnya saja, karena teks exception httpx bisa memuat URL.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

_TIMEOUT_S = 10.0


class DiscordTakTerjangkau(RuntimeError):
    """Tidak ada jawaban HTTP (jaringan, DNS, timeout). Pesannya tanpa URL."""


@dataclass(frozen=True)
class JawabanDiscord:
    status: int
    #: Detik yang diminta Discord sebelum mencoba lagi (429), dari badan atau header.
    retry_after: float | None


class DiscordClient:
    def __init__(self, url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url = url
        self._transport = transport

    async def kirim(self, isi: str) -> JawabanDiscord:
        # `allowed_mentions` kosong: teks galat yang kebetulan memuat @everyone tidak
        # boleh memanggil seluruh kanal.
        badan = {"content": isi, "allowed_mentions": {"parse": []}}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S, transport=self._transport) as client:
                res = await client.post(self._url, json=badan)
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            # `InvalidURL` bukan `HTTPError`, dan host IDNA yang rusak melempar
            # `idna.InvalidCodepoint` (turunan `ValueError`): alamat yang lolos pemeriksaan
            # awal tapi ditolak httpx tidak boleh lolos sebagai exception mentah dari sini.
            raise DiscordTakTerjangkau(type(exc).__name__) from None
        return JawabanDiscord(res.status_code, _retry_after(res))


def _retry_after(res: httpx.Response) -> float | None:
    try:
        badan = res.json()
    except ValueError:
        badan = None
    if isinstance(badan, dict) and isinstance(badan.get("retry_after"), (int, float)):
        return float(badan["retry_after"])
    try:
        return float(res.headers["retry-after"])
    except (KeyError, ValueError):
        return None
