"""Lane mesin Danger Zone di sisi LINE: hapus data, hapus/hitung rekaman.

Dirakit lewat `buat_router()` dengan dependensi disuntik, BUKAN diimpor dari
`core.dependencies`: modul itu (dan `routes/internal.py`) menarik torch, dan
semua test yang mengimpornya dilewati di CI. Fitur yang menghapus data harus
teruji di CI, jadi modul ini tidak boleh mengimpor torch, cv2, atau ultralytics
— `test_modul_tidak_menarik_torch_cv2_atau_ultralytics` menjaganya.

`main.py` memasangnya dengan `get_settings`, `get_runtime_state`, dan
`_jadwalkan_keluar` yang sama dengan router internal lain.

Rancangan: `docs/superpowers/specs/2026-09-25-danger-zone-design.md` §5.
"""
from __future__ import annotations

import hmac
import logging
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from ..core.config import Settings
from ..domain.bahaya import MODE_HAPUS
from ..services.hapus_data_line import hapus_rekaman, ringkas_rekaman, tulis_penanda
from ..workers.runtime_state import RuntimeState

logger = logging.getLogger(__name__)

#: Sama dengan `/internal/restart`: cukup bagi jawaban sampai ke konsol, tidak
#: cukup lama untuk membuat layar terasa menggantung.
JEDA_KELUAR_DETIK = 1.0


def _merekam(state: RuntimeState) -> bool:
    recorder = state.video_recorder
    return bool(recorder is not None and recorder.status().get("merekam"))


def buat_router(
    *,
    settings: Callable[[], Settings],
    state: Callable[[], RuntimeState],
    keluar: Callable[[float], None],
) -> APIRouter:
    """Router `/internal/...` Danger Zone untuk satu proses line."""

    async def verifikasi(x_internal_secret: Annotated[str | None, Header()] = None) -> None:
        # Pembanding waktu-tetap: secret ini membuka perintah yang menghapus data.
        if not hmac.compare_digest(
            (x_internal_secret or "").encode(), settings().internal_secret.encode()
        ):
            raise HTTPException(status_code=401, detail="Invalid internal secret")

    router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verifikasi)])

    @router.post("/hapus-data")
    async def hapus_data(
        mode: Annotated[str, Body()],
        diminta_oleh: Annotated[str, Body()] = "?",
    ) -> dict[str, Any]:
        """Tulis penanda lalu keluar; datanya dihapus saat boot berikutnya.

        Menjawab lebih dulu, keluar belakangan (pola `/internal/restart`): konsol
        yang melihat koneksi putus akan melaporkan gagal padahal berhasil.
        """
        if mode not in MODE_HAPUS:
            raise HTTPException(
                status_code=400, detail={"kode": "mode_asing", "pesan": f"mode {mode!r}"}
            )
        # Diperiksa lagi di sini, di proses yang benar-benar tahu keadaan line —
        # truk bisa dipasang di antara pemeriksaan konsol dan perintah ini.
        if state().current_assignment_id:
            raise HTTPException(
                status_code=409,
                detail={"kode": "truk_terpasang", "pesan": "line sedang memproses truk"},
            )
        s = settings()
        # Di artifacts/ milik line ini — lihat services/hapus_data_line.py.
        tulis_penanda(s.artifacts_dir, mode=mode, diminta_oleh=diminta_oleh, now=time.time())
        logger.warning(
            "Hapus data (%s) diminta %s — line keluar, data dihapus saat boot", mode, diminta_oleh
        )
        keluar(JEDA_KELUAR_DETIK)
        return {"status": "menghapus", "jeda_detik": JEDA_KELUAR_DETIK}

    @router.get("/rekam/berkas")
    async def rekam_berkas() -> dict[str, Any]:
        s = settings()
        return {
            "line_code": s.line_code,
            **ringkas_rekaman(s.videos_dir, s.line_code),
            "merekam": _merekam(state()),
        }

    @router.post("/rekam/hapus")
    async def rekam_hapus() -> dict[str, Any]:
        """Hapus rekaman milik line ini. Ditolak selama merekam: berkasnya
        sedang ditulis encoder, dan menghapusnya menghasilkan rekaman rusak."""
        if _merekam(state()):
            raise HTTPException(
                status_code=409,
                detail={"kode": "sedang_merekam", "pesan": "line sedang merekam"},
            )
        s = settings()
        hasil = hapus_rekaman(s.videos_dir, s.line_code)
        logger.warning(
            "Rekaman %s dihapus: %d berkas, %d byte", s.line_code, hasil["berkas"], hasil["bytes"]
        )
        return {"line_code": s.line_code, **hasil}

    return router
