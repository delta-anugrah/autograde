"""Penilai "AI line ini masih memproses?" untuk semua pemeriksa (batch 2.1).

Satu objek per proses line, dirakit `main.py`, dipakai tiga pembaca yang harus
selalu sepakat:

- coil ERROR PLC (`sehat_untuk_plc`, dipanggil `PlcWorker` tiap tick);
- `/health` (dan healthcheck Docker yang memanggilnya) lewat `HealthService`;
- kartu line di konsol, lewat blok `ai` di `/internal/status`.

Aturannya murni di `domain/kesehatan_ai.py`; di sini cuma membaca fakta dari
`RuntimeState` + kamera + lisensi, dan mencatat transisi ke log sekali
masing-masing (bukan tiap panggilan: PLC memanggil lima kali per detik).

Tanpa torch, cv2, atau ultralytics: test-nya harus jalan di CI.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from ..domain.kesehatan_ai import FaktaAi, PenilaianAi, ke_kawat, nilai_ai
from ..license.gate import grading_blocked

logger = logging.getLogger(__name__)


class KameraBerstatus(Protocol):
    """Yang dibaca penjaga dari kamera: cuma status sambungannya, dibaca tiap penilaian
    (reconnect mengubah `.connected` objek yang sama, bukan membuat objek baru)."""

    connected: bool


class PenjagaAi:
    def __init__(
        self,
        *,
        settings: Any,
        state: Any,
        kamera: KameraBerstatus,
        jam_dinding: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._state = state
        self._kamera = kamera
        self._jam_dinding = jam_dinding
        self._kunci = threading.Lock()
        self._mati_tercatat = False

    def nilai(self) -> PenilaianAi:
        return self._nilai_sekarang()[1]

    def sehat_untuk_plc(self) -> bool:
        """`health_check` untuk `PlcWorker`: False = naikkan coil ERROR."""
        return not self.nilai().error_plc

    def ringkas(self) -> dict[str, Any]:
        """Blok `ai` untuk `/health` dan `/internal/status` (sampai ke operator)."""
        sekarang, penilaian = self._nilai_sekarang()
        return ke_kawat(
            penilaian,
            ambang_detik=self._settings.ai_mati_detik,
            sekarang=sekarang,
            jam_dinding=self._jam_dinding(),
        )

    def ringkas_lengkap(self) -> dict[str, Any]:
        """`ringkas()` + galat terakhir, untuk `/health/detail` (support saja)."""
        return {
            **self.ringkas(),
            "galat_terakhir": self._state.ai_galat_terakhir,
            "galat_at": self._state.ai_galat_at or None,
        }

    def _nilai_sekarang(self) -> tuple[float, PenilaianAi]:
        """Baca jam, nilai, dan bandingkan dengan transisi terakhir dalam SATU
        kunci. Kalau jam dibaca di luar kunci, penilaian yang dihitung lebih
        dulu bisa tiba sesudah yang lebih baru dan membalik transisinya
        (PLC tiap 200 ms dan HTTP membaca bersamaan): satu kejadian jadi tiga
        baris log. Semuanya murni dan cuma mikrodetik; log tetap di luar."""
        s = self._state
        with self._kunci:
            sekarang = s.jam()
            penilaian = nilai_ai(
                FaktaAi(
                    sekarang=sekarang,
                    ambang_detik=self._settings.ai_mati_detik,
                    kamera_tersambung=bool(getattr(self._kamera, "connected", False)),
                    grading_diblokir=grading_blocked(self._settings.lic_enabled, s.license_exp),
                    dimulai_at=s.ai_dimulai_at,
                    frame_terakhir_at=s.frame_terakhir_at,
                    aliran_frame_sejak=s.aliran_frame_sejak,
                    inferensi_selesai_at=s.inferensi_selesai_at,
                )
            )
            berubah = penilaian.mati != self._mati_tercatat
            self._mati_tercatat = penilaian.mati
        if berubah:
            self._catat_transisi(penilaian, sekarang)
        return sekarang, penilaian

    def _galat_untuk_log(self, p: PenilaianAi, sekarang: float) -> str:
        """Galat terakhir itu sejak BOOT, bukan bukti sebab sekarang: yang terjadi
        sebelum AI berhenti (galat pagi yang sudah pulih) disebut umurnya, bukan
        disodorkan sebagai sebab."""
        galat, galat_at = self._state.ai_galat_terakhir, self._state.ai_galat_at
        if not galat:
            return "tidak ada (loop macet atau tidak menerima frame)"
        dinding = self._jam_dinding()
        mati_sejak = dinding - (sekarang - p.diam_sejak) if p.diam_sejak is not None else None
        if mati_sejak is None or galat_at >= mati_sejak:
            return galat
        return (
            f"tidak ada galat sejak AI berhenti (loop macet atau tidak menerima frame); "
            f"galat terakhir sejak boot {int(dinding - galat_at)} detik lalu: {galat}"
        )

    def _catat_transisi(self, p: PenilaianAi, sekarang: float) -> None:
        if p.mati:
            logger.error(
                "AI %s berhenti memproses (kode AI_MATI): kamera mengirim gambar tapi tidak "
                "ada frame yang selesai digrading selama lebih dari %s detik. Buah lewat "
                "tanpa disortir; coil ERROR naik kalau PLC aktif. Galat terakhir: %s",
                self._settings.line_code, self._settings.ai_mati_detik, self._galat_untuk_log(p, sekarang),
            )
        else:
            # Bukan "memproses lagi": keluar dari ai_mati bisa juga ke kamera_putus,
            # lisensi, atau sumber_diam, dan di sana AI tetap tidak memproses.
            logger.warning(
                "AI %s tidak lagi dinilai mati (keadaan %s)",
                self._settings.line_code, p.keadaan.value,
            )


def ringkas_ai_dari_state(state: Any, *, lengkap: bool = False) -> dict[str, Any] | None:
    """Blok `ai` dari `RuntimeState.penjaga_ai`, atau None kalau belum dipasang
    (line baru menyala, proses konsol, test yang tidak merakit penjaga)."""
    penjaga = getattr(state, "penjaga_ai", None)
    if penjaga is None:
        return None
    return penjaga.ringkas_lengkap() if lengkap else penjaga.ringkas()
