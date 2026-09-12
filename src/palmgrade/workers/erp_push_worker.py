"""Dorong event grading dari konsol ke PalmOS (ERP).

Arahnya **dorong**, dan itu bukan selera: PC pabrik cuma bisa dihubungi lewat
AnyDesk, tidak ada inbound sama sekali, jadi ERP tidak akan pernah bisa menarik
dari sini (runbook §12.5). Endpoint tujuannya satu — metode whitelisted
`palmos.interfaces.api.terima_event`, idempoten lewat `event_id`.

Antreannya tabel `inspections` itu sendiri, bukan tabel kedua: `erp_state IS
NULL` = belum didorong. Satu fakta di satu tempat — antrean terpisah selalu
berakhir beda isi dengan tabel yang dia bayangi.

Tiga kelas hasil, dan bedanya penting:

- **200** → mendarat (`{"baru": true}`) atau sudah pernah mendarat
  (`{"baru": false}`). Dua-duanya sukses; kiriman ulang setelah internet balik
  memang perilaku yang benar, bukan error.
- **417** → ERP menolak isinya (`frappe.throw`). Permanen. Ditandai `tolak` dan
  tidak pernah diputar lagi — payload cacat yang diulang selamanya cuma bikin
  antrean di belakangnya kelaparan.
- **sisanya** (jaringan mati, 5xx, 401/403) → kondisi luar, bukan salah barisnya.
  Kolomnya TIDAK disentuh, batch dihentikan, tick berikutnya mengambil ulang.
  401/403 dipisah lognya: itu kredensial salah, bukan internet putus, dan tanpa
  disebut sendiri dia tenggelam sebagai "gagal kirim" berhari-hari.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from ..core.config import Settings
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # payload teks kecil; link pabrik bisa lambat
_TOLAK = 417  # frappe.throw(ValidationError)


class _Berhenti(Exception):
    """Kondisi luar. Sisa batch percuma dilanjut pada tick ini."""


class ErpPushWorker:
    def __init__(self, settings: Settings, store: ConsoleStore) -> None:
        self.settings = settings
        self.store = store

    async def run_loop(self) -> None:
        if not self.settings.erp_url:
            logger.info("ErpPushWorker off — ERP_URL kosong")
            return
        logger.info("ErpPushWorker started — target: %s", self.settings.erp_events_url)
        while True:
            try:
                await self.push_once()
            except Exception:
                logger.exception("ErpPushWorker gagal — coba lagi tick berikutnya")
            await asyncio.sleep(self.settings.erp_push_interval_s)

    async def push_once(self) -> int:
        """Satu batch. Return jumlah baris yang mendarat di ERP."""
        rows = self.store.belum_didorong(self.settings.erp_push_batch)
        if not rows:
            return 0

        headers = {
            "Authorization": f"token {self.settings.erp_api_key}:{self.settings.erp_api_secret}"
        }
        mendarat = 0
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, headers=headers) as client:
            for row in rows:
                try:
                    mendarat += await self._kirim(client, row)
                except _Berhenti:
                    break
        logger.info("ERP push: %s dari %s baris mendarat", mendarat, len(rows))
        return mendarat

    async def _kirim(self, client: httpx.AsyncClient, row: dict) -> int:
        try:
            res = await client.post(self.settings.erp_events_url, json=_payload(row))
        except httpx.HTTPError as exc:
            logger.warning("ERP tidak terjangkau (%s) — antrean ditahan", exc)
            raise _Berhenti from exc

        if res.status_code == _TOLAK:
            # Alasannya ikut dicatat: ini satu-satunya jejak kenapa satu janjang
            # tidak pernah muncul di ERP.
            logger.error("ERP menolak %s permanen: %s", row["event_id"], res.text[:300])
            self.store.tandai_erp(row["event_id"], "tolak")
            return 0

        if res.status_code in (401, 403):
            logger.error("ERP menolak kredensial (%s) — cek ERP_API_KEY/SECRET dan Role "
                         "PalmOS AutoGrade. Antrean ditahan, tidak ada yang dibuang.",
                         res.status_code)
            raise _Berhenti

        if res.status_code >= 400:
            logger.warning("ERP balas %s — antrean ditahan", res.status_code)
            raise _Berhenti

        self.store.tandai_erp(row["event_id"], "ok")
        return 1


def _payload(row: dict) -> dict:
    """Baris konsol → kontrak §5. Field kosong dikirim apa adanya.

    Sengaja TIDAK menambal `prediction` atau `image_path` yang kosong: ERP
    menolaknya dengan alasan, barisnya jadi `tolak`, dan itu kelihatan di log.
    Menambalnya di sini berarti menebak, dan tebakan yang salah tidak pernah
    kelihatan sama sekali.
    """
    return {
        "event_id": row["event_id"],
        "machine_id": row["machine_id"],
        "timestamp": row["timestamp"],
        "prediction": row["prediction"],
        "capture_type": row["capture_type"],
        "image_path": row["image_path"],
        "truck_id": row["truck_id"],
        "tp_status": row["tp_status"],
        "tp_confidence": row["tp_confidence"],
        "ripeness_status": row["ripeness_status"],
        "ripeness_confidence": row["ripeness_confidence"],
    }
