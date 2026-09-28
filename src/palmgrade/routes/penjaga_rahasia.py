"""Dependensi FastAPI untuk lane perintah konsol ke line (`x-internal-secret`).

Modul sendiri, tanpa torch: `routes/internal.py` menarik torch lewat
`core.dependencies`, sedangkan penjaga ini harus teruji di CI dan dipakai juga
oleh `routes/internal_bahaya.py`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Header, HTTPException

from ..core.config import Settings
from ..domain.rahasia import rahasia_cocok


def penjaga_internal(settings: Callable[[], Settings]) -> Callable[..., Awaitable[None]]:
    async def verifikasi(x_internal_secret: Annotated[str | None, Header()] = None) -> None:
        if not rahasia_cocok(x_internal_secret, settings().internal_secret):
            raise HTTPException(status_code=401, detail="Invalid internal secret")

    return verifikasi
