"""Danger Zone — lima aksi berbahaya di tab Setelan, akun support saja.

Restart semua line, logout paksa semua akun, hapus rekaman video, hapus data
transaksi, hapus semua data. Keputusan boleh/tidak hidup di `domain/bahaya.py`;
di sini urutan kerjanya, dan urutan itu yang membuat penghapusan aman:

1. periksa ulang hambatan di server (layar tidak pernah dipercaya);
2. suruh tiap line menghapus datanya sendiri (penanda + keluar; dihapus saat
   boot — foto line di-mount read-only ke konsol);
3. TUNGGU line benar-benar mati: line keluar 1 detik sesudah menjawab, dan
   janjang yang lewat di detik itu masih dikirim ke konsol;
4. baru hapus data konsol, di tempat, lewat store yang sudah terbuka;
5. tulis jejak — sesudah log dikosongkan, jadi ia baris pertama log baru.

Jejak ditulis lewat `logger.warning`, bukan `LogStore.write` langsung, supaya
lewat `SqliteLogHandler` yang sama dengan semua log lain (termasuk `redact()`).

Rancangan: `docs/superpowers/specs/2026-09-25-danger-zone-design.md`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from ..core.config import LineEndpoint
from ..domain.bahaya import (
    MODE_HAPUS,
    MODE_SEMUA,
    MODE_TRANSAKSI,
    KeadaanKonsol,
    KeadaanLine,
    hambatan_hapus_data,
    hambatan_mode_semua,
    konfirmasi_sah,
    peringatan_hapus_data,
    peringatan_hapus_rekaman,
    peringatan_restart,
)
from ..domain.operator_error import OperatorError
from ..integrations.erp.outbox_store import ErpOutboxStore
from ..integrations.notifications.line_client import LinePlcTolak, LineUnavailable
from ..repositories.console_repository import ConsoleStore
from ..repositories.log_repository import LogStore
from .akun_bawaan import seed_default_accounts

logger = logging.getLogger(__name__)


class BahayaTidakSah(OperatorError):
    """400 — permintaannya sendiri tidak sah: konfirmasi salah atau mode asing."""


class BahayaDitolak(OperatorError):
    """409 — keadaan pabrik belum aman untuk menghapus. Tidak ada yang berubah."""

    def __init__(self, hambatan: list[dict]) -> None:
        kode = ",".join(h["kode"] for h in hambatan)
        super().__init__("bahaya_ditolak", f"ditolak: {kode}", hambatan=kode)
        self.hambatan = hambatan


def _kode_tolak(exc: LinePlcTolak) -> str:
    """Kode penolakan line (`truk_terpasang`, `sedang_merekam`) dari badan 409-nya."""
    try:
        detail = json.loads(exc.detail).get("detail", {})
        if isinstance(detail, dict) and detail.get("kode"):
            return str(detail["kode"])
    except (ValueError, AttributeError):
        pass
    return "ditolak"


class BahayaService:
    def __init__(
        self,
        store: ConsoleStore,
        log_store: LogStore,
        line_client: Any,
        lines: tuple[LineEndpoint, ...],
        erp_outbox: ErpOutboxStore,
        manifest_outbox: ErpOutboxStore | None = None,
        *,
        erp_aktif: bool,
        hash_bawaan: str = "",
        hash_support: str = "",
        tarik_master: Callable[[], Awaitable[Any]] | None = None,
        tunggu_mati_s: float = 5.0,
        jeda_cek_s: float = 0.25,
    ) -> None:
        self._store = store
        self._log = log_store
        self._line_client = line_client
        self._lines = lines
        self._erp_outbox = erp_outbox
        # None kalau R2 tidak disetel — tidak ada antrean manifest sama sekali.
        self._manifest_outbox = manifest_outbox
        self._erp_aktif = erp_aktif
        self._hash_bawaan = hash_bawaan
        self._hash_support = hash_support
        self._tarik_master = tarik_master
        self._tunggu_mati_s = tunggu_mati_s
        self._jeda_cek_s = jeda_cek_s
        # Aksi yang mengubah sesuatu dijalankan satu per satu: dua support yang
        # menekan bersamaan tidak boleh saling menyilang di tengah penghapusan.
        self._kunci = asyncio.Lock()

    # ── keadaan ─────────────────────────────────────────────────────────────

    async def _satu_line(self, line: LineEndpoint) -> KeadaanLine:
        try:
            detail = await self._line_client.health_detail(line)
        except LineUnavailable:
            return KeadaanLine(line.line_code, terjangkau=False)
        try:
            rekam = await self._line_client.rekam_berkas(line)
        except LineUnavailable:
            # Line versi lama tanpa lane ini: rekamannya tidak diketahui, dan
            # itu tidak boleh membuat line terbaca mati.
            rekam = {}
        pending = detail.get("outbox_pending")
        return KeadaanLine(
            line.line_code,
            terjangkau=True,
            truk_terpasang=bool(detail.get("current_assignment_id")),
            outbox_pending=pending if isinstance(pending, int) else None,
            merekam=bool(rekam.get("merekam")),
            rekaman_berkas=int(rekam.get("berkas") or 0),
            rekaman_bytes=int(rekam.get("bytes") or 0),
        )

    async def _keadaan_lines(self) -> list[KeadaanLine]:
        return list(await asyncio.gather(*(self._satu_line(ln) for ln in self._lines)))

    def _keadaan_konsol(self) -> KeadaanKonsol:
        return KeadaanKonsol(
            erp_aktif=self._erp_aktif,
            erp_pending=self._erp_outbox.pending_count(),
            erp_gagal=self._erp_outbox.failed_count(),
            akun_bawaan=bool(self._hash_bawaan or self._hash_support),
        )

    def _hambatan(self, mode: str, lines: list[KeadaanLine], konsol: KeadaanKonsol) -> list[dict]:
        hambatan = hambatan_hapus_data(lines, konsol)
        if mode == MODE_SEMUA:
            hambatan += hambatan_mode_semua(konsol)
        return hambatan

    async def ringkasan(self) -> dict[str, Any]:
        """Angka, hambatan, dan peringatan untuk kelima panel sekaligus."""
        lines = await self._keadaan_lines()
        konsol = self._keadaan_konsol()
        data = self._store.ringkas_data(now=time.time())
        return {
            "lines": [asdict(ln) for ln in lines],
            "data": data,
            "antrean_erp": {
                "aktif": konsol.erp_aktif,
                "pending": konsol.erp_pending,
                "gagal": konsol.erp_gagal,
            },
            "aksi": {
                "restart": {"peringatan": peringatan_restart(lines)},
                "logout": {"sesi_aktif": data["sesi_aktif"]},
                "rekaman": {
                    "berkas": sum(ln.rekaman_berkas for ln in lines),
                    "bytes": sum(ln.rekaman_bytes for ln in lines),
                    "peringatan": peringatan_hapus_rekaman(lines),
                },
                MODE_TRANSAKSI: {
                    "hambatan": self._hambatan(MODE_TRANSAKSI, lines, konsol),
                    "peringatan": peringatan_hapus_data(lines, konsol, MODE_TRANSAKSI),
                },
                MODE_SEMUA: {
                    "hambatan": self._hambatan(MODE_SEMUA, lines, konsol),
                    "peringatan": peringatan_hapus_data(lines, konsol, MODE_SEMUA),
                },
            },
        }

    # ── aksi ────────────────────────────────────────────────────────────────

    async def restart_semua(self, *, oleh: str) -> dict[str, Any]:
        """Restart ketiga line (mekanisme Sumber Kamera: line keluar, Docker
        menyalakannya lagi). Tidak pernah diblokir; hasilnya per line."""
        async with self._kunci:
            hasil = []
            for line in self._lines:
                try:
                    await self._line_client.restart(line)
                    hasil.append({"line_code": line.line_code, "ok": True})
                except LineUnavailable as exc:
                    hasil.append({"line_code": line.line_code, "ok": False, "alasan": str(exc)[:200]})
            logger.warning(
                "[Danger Zone] Restart semua line oleh %s: %s",
                oleh, ", ".join(f"{r['line_code']}={'ok' if r['ok'] else 'gagal'}" for r in hasil),
            )
            return {"lines": hasil}

    def logout_semua(self, *, oleh: str) -> dict[str, int]:
        """Hapus semua sesi — layar operator di PC pabrik dan yang menekan ikut keluar."""
        jumlah = self._store.hapus_semua_sesi()
        logger.warning("[Danger Zone] Logout paksa semua akun oleh %s: %d sesi dihapus", oleh, jumlah)
        return {"sesi_dihapus": jumlah}

    async def hapus_rekaman(self, *, konfirmasi: str | None, oleh: str) -> dict[str, Any]:
        """Tiap line menghapus rekaman miliknya. Line yang merekam menolak, line
        yang mati dilewati — keduanya disebut di hasil, rekamannya tetap ada."""
        if not konfirmasi_sah(konfirmasi):
            raise BahayaTidakSah("konfirmasi_salah", "ketik HAPUS untuk melanjutkan")
        async with self._kunci:
            hasil = []
            for line in self._lines:
                try:
                    r = await self._line_client.rekam_hapus(line)
                    hasil.append({
                        "line_code": line.line_code, "ok": True,
                        "berkas": int(r.get("berkas") or 0), "bytes": int(r.get("bytes") or 0),
                    })
                except LinePlcTolak as exc:
                    hasil.append({"line_code": line.line_code, "ok": False, "kode": _kode_tolak(exc)})
                except LineUnavailable:
                    hasil.append({"line_code": line.line_code, "ok": False, "kode": "line_mati"})
            berkas = sum(r.get("berkas", 0) for r in hasil)
            total = sum(r.get("bytes", 0) for r in hasil)
            logger.warning(
                "[Danger Zone] Rekaman video dihapus oleh %s: %d berkas, %.2f GB (%s)",
                oleh, berkas, total / 1e9,
                ", ".join(f"{r['line_code']}={'ok' if r['ok'] else r['kode']}" for r in hasil),
            )
            return {"lines": hasil, "berkas": berkas, "bytes": total}

    async def hapus_data(self, *, mode: str, konfirmasi: str | None, oleh: str) -> dict[str, Any]:
        """Hapus data transaksi (atau semua data) di ketiga line dan konsol."""
        if mode not in MODE_HAPUS:
            raise BahayaTidakSah("mode_asing", f"mode {mode!r} tidak dikenal", mode=mode)
        if not konfirmasi_sah(konfirmasi):
            raise BahayaTidakSah("konfirmasi_salah", "ketik HAPUS untuk melanjutkan")
        async with self._kunci:
            lines = await self._keadaan_lines()
            hambatan = self._hambatan(mode, lines, self._keadaan_konsol())
            if hambatan:
                logger.warning(
                    "[Danger Zone] Hapus data %s oleh %s DITOLAK: %s",
                    mode, oleh, ", ".join(h["kode"] for h in hambatan),
                )
                raise BahayaDitolak(hambatan)

            hasil_line = []
            for line in self._lines:
                try:
                    await self._line_client.hapus_data(line, mode=mode, diminta_oleh=oleh)
                    hasil_line.append({"line_code": line.line_code, "ok": True})
                except LinePlcTolak as exc:
                    hasil_line.append({"line_code": line.line_code, "ok": False, "kode": _kode_tolak(exc)})
                except LineUnavailable:
                    hasil_line.append({"line_code": line.line_code, "ok": False, "kode": "line_mati"})

            diterima = [ln for ln, r in zip(self._lines, hasil_line, strict=True) if r["ok"]]
            await self._tunggu_mati(diterima)

            # Konsol tetap dikosongkan walau ada line yang gagal: layar yang
            # masih menampilkan data yang separuhnya sudah dihapus lebih buruk
            # daripada satu line yang disebut gagal dan tinggal diulang.
            konsol = self._store.hapus_data(mode)
            antrean = self._erp_outbox.hapus_semua()
            if self._manifest_outbox is not None:
                antrean += self._manifest_outbox.hapus_semua()
            self._log.hapus_semua()
            if mode == MODE_SEMUA:
                seed_default_accounts(
                    self._store, hash_bawaan=self._hash_bawaan, hash_support=self._hash_support
                )
                await self._tarik_master_sekarang()

            logger.warning(
                "[Danger Zone] Data %s dihapus oleh %s: %d janjang, %d tiket, %d antrean; line %s",
                mode, oleh, konsol.get("inspections", 0), konsol.get("weighings", 0), antrean,
                ", ".join(f"{r['line_code']}={'ok' if r['ok'] else r['kode']}" for r in hasil_line),
            )
            return {"mode": mode, "lines": hasil_line, "konsol": {**konsol, "antrean": antrean}}

    # ── privat ──────────────────────────────────────────────────────────────

    async def _tunggu_mati(self, lines: list[LineEndpoint]) -> None:
        if not lines or self._tunggu_mati_s <= 0:
            return
        batas = time.monotonic() + self._tunggu_mati_s
        sisa = list(lines)
        while sisa and time.monotonic() < batas:
            hidup = await asyncio.gather(*(self._line_client.hidup(ln) for ln in sisa))
            sisa = [ln for ln, h in zip(sisa, hidup, strict=True) if h]
            if sisa:
                await asyncio.sleep(self._jeda_cek_s)
        if sisa:
            logger.warning(
                "[Danger Zone] %s belum mati sesudah %.0f detik — data konsol tetap dihapus",
                ", ".join(ln.line_code for ln in sisa), self._tunggu_mati_s,
            )

    async def _tarik_master_sekarang(self) -> None:
        """Truk, supplier, dan akun AutoERP turun lagi sekarang, bukan menunggu
        tick `CONSOLE_SYNC_INTERVAL_S`. Gagal = tarikan terjadwal yang membawanya."""
        if self._tarik_master is None:
            return
        try:
            await self._tarik_master()
        except Exception as exc:  # noqa: BLE001 — hapus sudah terjadi; ini pelengkap
            logger.warning("[Danger Zone] Tarikan master data sesudah hapus gagal: %s", exc)
