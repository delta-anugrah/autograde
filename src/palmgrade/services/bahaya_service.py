"""Danger Zone — lima aksi berbahaya di tab Setelan, akun support saja.

Restart semua line, logout paksa semua akun, hapus rekaman video, hapus data
transaksi, hapus semua data. Keputusan boleh/tidak hidup di `domain/bahaya.py`;
di sini urutan kerjanya, dan urutan itu yang membuat penghapusan aman:

1. kunci penugasan truk (`store.hapus_berjalan`), lalu periksa ulang hambatan
   di server (layar tidak pernah dipercaya);
2. suruh ketiga line BERSAMAAN menghapus datanya sendiri (penanda + keluar;
   dihapus saat boot — foto line di-mount read-only ke konsol). Tidak satu
   line pun menerima = berhenti di sini, tidak ada yang dihapus;
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
from .akun_bawaan import hash_is_usable, seed_default_accounts

logger = logging.getLogger(__name__)


class BahayaTidakSah(OperatorError):
    """400 — permintaannya sendiri tidak sah: konfirmasi salah atau mode asing."""


class BahayaDitolak(OperatorError):
    """409 — keadaan pabrik belum aman untuk menghapus. Tidak ada yang berubah."""

    def __init__(self, hambatan: list[dict]) -> None:
        kode = ",".join(h["kode"] for h in hambatan)
        super().__init__("bahaya_ditolak", f"ditolak: {kode}", hambatan=kode)
        self.hambatan = hambatan


class BahayaSemuaMenolak(OperatorError):
    """409 — tidak satu line pun menerima perintah hapus. Tidak ada yang berubah."""

    def __init__(self, hasil_line: list[dict]) -> None:
        ringkas = ",".join(f"{r['line_code']}:{r.get('kode', 'ok')}" for r in hasil_line)
        super().__init__("semua_line_menolak", f"semua line menolak: {ringkas}", lines=ringkas)
        self.lines = hasil_line


#: Penolakan line yang tidak membawa kode sendiri, dibaca dari status HTTP-nya.
_KODE_STATUS = {
    # Line versi lama: rute Danger Zone belum ada di image-nya.
    404: "versi_lama",
    # Middleware lisensi line menolak SEMUA `/internal/*` begitu langganan habis.
    403: "lisensi",
}


def _kode_tolak(exc: LinePlcTolak) -> str:
    """Kode penolakan line: dari badan jawabannya (`truk_terpasang`,
    `sedang_merekam`), kalau tidak ada dari status HTTP-nya."""
    try:
        detail = json.loads(exc.detail).get("detail", {})
        if isinstance(detail, dict) and detail.get("kode"):
            return str(detail["kode"])
    except (ValueError, AttributeError):
        pass
    return _KODE_STATUS.get(exc.status_code, "ditolak")


def _ringkas_hasil(hasil: list[dict]) -> str:
    return ", ".join(f"{r['line_code']}={r.get('kode', 'ok')}" for r in hasil)


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
        hari_kerja: Callable[[], str],
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
        self._hari_kerja = hari_kerja
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
        gagal = detail.get("outbox_failed")
        return KeadaanLine(
            line.line_code,
            terjangkau=True,
            truk_terpasang=bool(detail.get("current_assignment_id")),
            outbox_pending=pending if isinstance(pending, int) else None,
            outbox_gagal=gagal if isinstance(gagal, int) else None,
            merekam=bool(rekam.get("merekam")),
            rekaman_berkas=int(rekam.get("berkas") or 0),
            rekaman_bytes=int(rekam.get("bytes") or 0),
        )

    async def _keadaan_lines(self) -> list[KeadaanLine]:
        return list(await asyncio.gather(*(self._satu_line(ln) for ln in self._lines)))

    def _keadaan_konsol(self) -> KeadaanKonsol:
        tiket = self._store.tiket_terbuka(self._hari_kerja())
        return KeadaanKonsol(
            erp_aktif=self._erp_aktif,
            erp_pending=self._erp_outbox.pending_count(),
            erp_gagal=self._erp_outbox.failed_count(),
            # Aturan yang sama dengan `seed_default_accounts`: hash yang tidak
            # terbaca tidak pernah jadi akun, jadi tidak dihitung sebagai jalan kembali.
            akun_support_bawaan=hash_is_usable(self._hash_support),
            tiket_terbuka=tiket["hari_ini"],
            tiket_lama_terbuka=tiket["lama"],
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
                oleh, berkas, total / 1e9, _ringkas_hasil(hasil),
            )
            return {"lines": hasil, "berkas": berkas, "bytes": total}

    async def hapus_data(self, *, mode: str, konfirmasi: str | None, oleh: str) -> dict[str, Any]:
        """Hapus data transaksi (atau semua data) di ketiga line dan konsol."""
        if mode not in MODE_HAPUS:
            raise BahayaTidakSah("mode_asing", f"mode {mode!r} tidak dikenal", mode=mode)
        if not konfirmasi_sah(konfirmasi):
            raise BahayaTidakSah("konfirmasi_salah", "ketik HAPUS untuk melanjutkan")
        async with self._kunci:
            # Dikunci SEBELUM pemeriksaan ulang: truk yang dipasang di antara
            # pemeriksaan dan perintah tidak terlihat oleh keduanya.
            self._store.hapus_berjalan = True
            try:
                return await self._hapus_data(mode, oleh)
            finally:
                self._store.hapus_berjalan = False

    async def _hapus_data(self, mode: str, oleh: str) -> dict[str, Any]:
        lines = await self._keadaan_lines()
        hambatan = self._hambatan(mode, lines, self._keadaan_konsol())
        if hambatan:
            logger.warning(
                "[Danger Zone] Hapus data %s oleh %s DITOLAK: %s",
                mode, oleh, ", ".join(h["kode"] for h in hambatan),
            )
            raise BahayaDitolak(hambatan)

        # Bersamaan, bukan berurutan: satu line yang lambat menjawab tidak boleh
        # membuat line lain sudah restart sementara yang terakhir belum ditanya.
        jawaban = await asyncio.gather(
            *(self._perintah_hapus(line, mode, oleh) for line in self._lines)
        )
        hasil_line = [hasil for hasil, _jeda in jawaban]
        diterima = [ln for ln, r in zip(self._lines, hasil_line, strict=True) if r["ok"]]
        if not diterima:
            # Foto semua line masih utuh: mengosongkan konsol sekarang membuang
            # index yang menunjuk ke sana, tanpa satu berkas pun berkurang.
            logger.warning(
                "[Danger Zone] Hapus data %s oleh %s GAGAL: tidak ada line yang menerima (%s)"
                " — tidak ada yang dihapus", mode, oleh, _ringkas_hasil(hasil_line),
            )
            raise BahayaSemuaMenolak(hasil_line)

        belum_mati = await self._tunggu_mati(diterima, jeda=max(j for _hasil, j in jawaban))
        for r in hasil_line:
            if r["line_code"] in belum_mati:
                r["kode"] = "belum_mati"

        # Konsol tetap dikosongkan walau ada line yang gagal: layar yang masih
        # menampilkan data yang separuhnya sudah dihapus lebih buruk daripada
        # satu line yang disebut gagal dan tinggal diulang.
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
            _ringkas_hasil(hasil_line),
        )
        return {"mode": mode, "lines": hasil_line, "konsol": {**konsol, "antrean": antrean}}

    # ── privat ──────────────────────────────────────────────────────────────

    async def _perintah_hapus(
        self, line: LineEndpoint, mode: str, oleh: str
    ) -> tuple[dict[str, Any], float]:
        """Hasil satu line + berapa detik ia masih hidup sesudah menjawab."""
        try:
            jawaban = await self._line_client.hapus_data(line, mode=mode, diminta_oleh=oleh)
        except LinePlcTolak as exc:
            return {"line_code": line.line_code, "ok": False, "kode": _kode_tolak(exc)}, 0.0
        except LineUnavailable:
            return {"line_code": line.line_code, "ok": False, "kode": "line_mati"}, 0.0
        jeda = jawaban.get("jeda_detik") if isinstance(jawaban, dict) else None
        return {"line_code": line.line_code, "ok": True}, float(jeda or 0)

    async def _tunggu_mati(self, lines: list[LineEndpoint], *, jeda: float) -> set[str]:
        """Tunggu sampai tiap line DUA KALI berturut-turut tidak menjawab `/health`.

        Kembalikan kode line yang belum mati sampai batas waktu: perintahnya sudah
        diterima (penanda tertulis, datanya dihapus saat line itu restart), tapi
        janjang yang lewat sementara itu masih bisa mendarat di konsol.
        """
        if not lines or self._tunggu_mati_s <= 0:
            return set()
        batas = time.monotonic() + self._tunggu_mati_s
        # Line masih hidup `jeda` detik sesudah menjawab (pola `/internal/restart`):
        # bertanya selama itu cuma membuang pertanyaan.
        await asyncio.sleep(min(max(jeda, 0.0), self._tunggu_mati_s))
        diam = {ln.line_code: 0 for ln in lines}
        sisa = list(lines)
        while sisa and time.monotonic() < batas:
            hidup = await asyncio.gather(*(self._line_client.hidup(ln) for ln in sisa))
            for ln, h in zip(sisa, hidup, strict=True):
                diam[ln.line_code] = 0 if h else diam[ln.line_code] + 1
            # Dua kali berturut-turut: satu tenggat yang lewat (line sibuk menulis
            # foto) bukan line yang mati.
            sisa = [ln for ln in sisa if diam[ln.line_code] < 2]
            if sisa:
                await asyncio.sleep(self._jeda_cek_s)
        if sisa:
            logger.warning(
                "[Danger Zone] %s belum mati sesudah %.0f detik — data konsol tetap dihapus",
                ", ".join(ln.line_code for ln in sisa), self._tunggu_mati_s,
            )
        return {ln.line_code for ln in sisa}

    async def _tarik_master_sekarang(self) -> None:
        """Truk, supplier, dan akun AutoERP turun lagi sekarang, bukan menunggu
        tick `CONSOLE_SYNC_INTERVAL_S`. Gagal = tarikan terjadwal yang membawanya."""
        if self._tarik_master is None:
            return
        try:
            await self._tarik_master()
        except Exception as exc:  # noqa: BLE001 — hapus sudah terjadi; ini pelengkap
            logger.warning("[Danger Zone] Tarikan master data sesudah hapus gagal: %s", exc)
