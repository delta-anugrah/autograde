"""Cek ringan tiap menit ke AutoERP (`ping`) dan R2 (`head_object`) untuk Last Sync.

Tanpa ini status sambungan cuma bergerak saat ada yang dikirim: tarikan data AutoERP
tiap 5 menit, foto tiap jam. Konsol yang putus jam 13:01 akan tetap tampil hijau sampai
jam 14:00. Cek ini TIDAK menggeser jam Last Sync (tidak ada data yang lewat), cuma
warnanya.

Sambungan yang tidak dipakai (`ERP_URL` / `R2_BUCKET` kosong) tidak dicek sama sekali.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from ..core.config import Settings
from ..integrations.erp.client import ErpClient
from ..integrations.erp.client import galat_jaringan as galat_jaringan_erp
from ..integrations.upload.r2_uploader import R2Uploader
from ..integrations.upload.r2_uploader import galat_jaringan as galat_jaringan_r2
from ..services.status_sinkron import StatusSinkron

logger = logging.getLogger(__name__)

_INTERVAL_S = 60


class _Pingable(Protocol):
    async def ping(self) -> None: ...


class _Cekable(Protocol):
    def cek(self) -> None: ...


class CekSinkronWorker:
    def __init__(
        self,
        status: StatusSinkron,
        *,
        erp: _Pingable | None,
        r2: _Cekable | None,
        interval_s: int = _INTERVAL_S,
    ) -> None:
        self._status = status
        self._erp = erp
        self._r2 = r2
        self._interval_s = interval_s

    async def run_once(self) -> None:
        # Exception apa pun berarti cek ini gagal; sebabnya ada di pesan. Tanpa jawaban
        # dicatat sebagai jaringan, penolakan (kunci salah, 500) sebagai cek yang gagal.
        if self._erp is not None:
            try:
                await self._erp.ping()
            except Exception as exc:  # noqa: BLE001
                self._status.gagal("erp", "cek", str(exc), jaringan=galat_jaringan_erp(exc))
            else:
                self._status.berhasil("erp", "cek", sinkron=False)
        if self._r2 is not None:
            try:
                # boto3 memblok; di thread supaya loop yang melayani layar tidak ikut diam.
                await asyncio.to_thread(self._r2.cek)
            except Exception as exc:  # noqa: BLE001
                self._status.gagal("r2", "cek", str(exc), jaringan=galat_jaringan_r2(exc))
            else:
                self._status.berhasil("r2", "cek", sinkron=False)

    async def run_loop(self) -> None:
        logger.info("CekSinkronWorker started, every %ss", self._interval_s)
        while True:
            # Aturan 6: loop tidak boleh mati karena satu putaran yang melempar.
            try:
                await self.run_once()
            except Exception:
                logger.exception("Last Sync check failed; retrying next tick")
            await asyncio.sleep(self._interval_s)


def build_cek_sinkron(settings: Settings, status: StatusSinkron) -> CekSinkronWorker | None:
    """Cek tiap menit untuk sambungan yang dipakai saja; None kalau dua-duanya kosong."""
    erp = ErpClient(settings.erp_url, settings.erp_api_key, settings.erp_api_secret) if settings.erp_url else None
    r2 = (
        R2Uploader(
            account_id=settings.r2_account_id,
            access_key_id=settings.r2_access_key_id,
            secret_access_key=settings.r2_secret_access_key,
            bucket=settings.r2_bucket,
        )
        if settings.r2_bucket
        else None
    )
    if erp is None and r2 is None:
        return None
    return CekSinkronWorker(status, erp=erp, r2=r2)
