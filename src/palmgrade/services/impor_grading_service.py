"""Impor grading dari CSV Per janjang (tab Riwayat, khusus support).

Dua langkah, supaya tidak ada yang tersimpan sebelum dilihat:

1. **Periksa**: baca berkas, hitung yang baru / sudah ada / hari berjalan / salah.
   Tidak menulis apa pun.
2. **Impor**: berkas yang SAMA (sidik sha256 dicocokkan), dibaca ulang dari awal dan
   ditolak utuh kalau ada satu baris salah. Janjang ditulis per potongan (lock konsol
   dilepas di antaranya, jadi kiriman janjang dari line tidak menunggu), ditandai
   `import_batch`, dan satu impor bisa dibatalkan utuh.

Yang sengaja TIDAK dilakukan: janjang hari ini dan sesudahnya tidak diimpor (masih
berjalan, dan ikut kunjungan truk yang dikirim ke AutoERP); janjang impor tidak
punya `assignment_id`, jadi tidak pernah masuk pesan kunjungan ke AutoERP; truk baru
tidak dikirim ke AutoERP, dan tidak dihapus saat impor dibatalkan (truk manual yang
tertinggal tidak mengganggu apa pun, sedangkan memastikan tidak ada janjang lain yang
memakainya berarti memindai seluruh tabel janjang di balik lock konsol).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from ..core.config import LineEndpoint
from ..domain.impor_grading import (
    MAKS_BYTE,
    JanjangImpor,
    SalahBaris,
    baca,
    hari_berjalan,
    sidik,
    timestamp_utc,
)
from ..domain.operator_error import (
    IMPOR_ADA_SALAH,
    IMPOR_BERJALAN,
    IMPOR_HAPUS_BERJALAN,
    IMPOR_KOSONG,
    IMPOR_SIDIK_BEDA,
    IMPOR_SUDAH_DIBATALKAN,
    IMPOR_TERLALU_BESAR,
    IMPOR_TIDAK_ADA,
    IMPOR_TIDAK_ADA_BARU,
    InvalidInput,
    OperatorError,
)
from ..domain.plate import normalisasi_plat, truck_id_for
from ..domain.vision_event import TP_PASS, prediction_for
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)

_CONTOH_SALAH = 50
_CONTOH_TRUK = 20
_POTONG = 500
# Pembatalan per 500 janjang, dengan jeda singkat di antaranya: `threading.Lock` tidak
# antre, jadi tanpa jeda thread ini merebut lock lagi sebelum ingest janjang dari line
# (di loop asyncio) sempat masuk, dan layar operator ikut membeku selama pembatalan.
_POTONG_BATAL = 500
_JEDA_BATAL_S = 0.01
#: TP di berkas cuma "ya": angka keyakinannya tidak diekspor. Nilai di atas ambang
#: `> 0.8` supaya hitungan TP di Riwayat dan Rekap sama dengan sebelum diekspor.
_TP_KEYAKINAN = 1.0


class ImporDitolak(OperatorError):
    """Keadaan yang menolak (409): berkas berubah, ada baris salah, impor lain berjalan."""


class ImporTidakAda(OperatorError):
    """Batch impor yang diminta tidak ada (404)."""


@dataclass
class _Hitungan:
    baris: int = 0
    baru: int = 0
    sudah_ada: int = 0
    ganda: int = 0
    hari_berjalan: int = 0
    salah: int = 0
    contoh_salah: list[dict[str, Any]] = field(default_factory=list)
    dari: str | None = None
    sampai: str | None = None
    per_line: dict[str, int] = field(default_factory=dict)
    #: Truk yang dibuat impor ini, dihitung per potongan supaya impor yang terputus
    #: tetap mencatat truk yang sudah terlanjur dibuat.
    truk_dibuat: int = 0

    def catat_baru(self, janjang: JanjangImpor) -> None:
        self.dari = min(self.dari or janjang.work_date, janjang.work_date)
        self.sampai = max(self.sampai or janjang.work_date, janjang.work_date)
        self.per_line[janjang.line_code] = self.per_line.get(janjang.line_code, 0) + 1


class ImporGradingService:
    def __init__(
        self,
        store: ConsoleStore,
        *,
        lines: tuple[LineEndpoint, ...],
        zona: str,
        hari_ini: Callable[[], str],
        jam: Callable[[], float] = time.time,
        id_baru: Callable[[], str] = lambda: str(uuid.uuid4()),
        potong: int = _POTONG,
        potong_batal: int = _POTONG_BATAL,
        jeda: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = store
        self._by_code = {ln.line_code: ln for ln in lines}
        self._zona = ZoneInfo(zona)
        self._hari_ini = hari_ini
        self._jam = jam
        self._id_baru = id_baru
        self._potong = potong
        self._potong_batal = potong_batal
        self._jeda = jeda
        # Satu impor atau pembatalan pada satu waktu. Di memori: konsol yang restart di
        # tengah impor tidak sedang mengimpor apa pun, dan batch-nya ditandai terputus.
        self._kunci = threading.Lock()
        store.tandai_impor_terputus()

    # ------------------------------------------------------------- periksa

    def periksa(self, isi: bytes, *, nama_berkas: str) -> dict[str, Any]:
        """Apa yang akan terjadi kalau berkas ini diimpor. Tidak menulis apa pun."""
        _cek_ukuran(isi)
        hari_ini = self._hari_ini()
        h = _Hitungan()
        peta_truk = self._store.peta_truk_per_plat()
        truk_baru: dict[str, str] = {}
        for potongan in self._potongan(isi, h, hari_ini):
            ada = self._store.event_sudah_ada([j.event_id for j in potongan])
            for j in potongan:
                if j.event_id in ada:
                    h.sudah_ada += 1
                    continue
                h.baru += 1
                h.catat_baru(j)
                if j.plat:
                    kunci = normalisasi_plat(j.plat)
                    if kunci not in peta_truk:
                        truk_baru.setdefault(kunci, j.plat)
        if h.baris == 0:
            raise InvalidInput(IMPOR_KOSONG, "berkas tanpa baris data")
        return {
            "sidik": sidik(isi),
            "nama_berkas": nama_berkas,
            "hari_ini": hari_ini,
            "baris": h.baris,
            "baru": h.baru,
            "sudah_ada": h.sudah_ada,
            "ganda": h.ganda,
            "hari_berjalan": h.hari_berjalan,
            "salah": h.salah,
            "contoh_salah": h.contoh_salah,
            "dari": h.dari,
            "sampai": h.sampai,
            "per_line": [
                {"line_code": kode, "jumlah": n, "dikenal": kode in self._by_code}
                for kode, n in sorted(h.per_line.items())
            ],
            "truk_baru": list(truk_baru.values())[:_CONTOH_TRUK],
            "truk_baru_jumlah": len(truk_baru),
            "bisa_impor": h.salah == 0 and h.baru > 0,
        }

    # --------------------------------------------------------------- impor

    def impor(self, isi: bytes, *, nama_berkas: str, sidik: str, oleh: str) -> dict[str, Any]:
        """Simpan berkas yang sudah diperiksa. Kembalikan catatan batch-nya."""
        _cek_ukuran(isi)
        if _sidik(isi) != sidik:
            raise ImporDitolak(IMPOR_SIDIK_BEDA, "berkas berubah sejak diperiksa")
        if not self._kunci.acquire(blocking=False):
            raise ImporDitolak(IMPOR_BERJALAN, "impor lain sedang berjalan")
        try:
            # Dicatat SEBELUM berkas diperiksa: penghapusan Danger Zone yang mulai dan
            # selesai selama pemeriksaan tetap ketahuan lewat hitungannya.
            hapus_ke = self._store.jumlah_hapus
            self._cek_hapus(hapus_ke)
            cek = self.periksa(isi, nama_berkas=nama_berkas)
            if cek["salah"]:
                raise ImporDitolak(IMPOR_ADA_SALAH, "berkas punya baris salah", jumlah=cek["salah"])
            if not cek["baru"]:
                raise ImporDitolak(IMPOR_TIDAK_ADA_BARU, "semua janjang sudah ada")
            self._cek_hapus(hapus_ke)
            batch_id = self._id_baru()
            self._store.mulai_impor({
                "id": batch_id, "file_name": nama_berkas, "fingerprint": sidik,
                "imported_by": oleh, "started_at": self._jam(), "rows_total": cek["baris"],
            })
            h = _Hitungan()
            try:
                self._tulis(isi, batch_id, h, cek["hari_ini"], hapus_ke)
            except BaseException:
                # Yang sudah tertulis tetap bertanda batch ini: bisa dibatalkan utuh.
                self._selesai(batch_id, h, status="interrupted")
                raise
            self._selesai(batch_id, h, status="done")
        finally:
            self._kunci.release()
        batch = self._store.impor_grading(batch_id) or {}
        logger.warning(
            "Impor grading %s oleh %s: %s janjang ditambah dari %s (%s s/d %s), %s sudah ada, "
            "%s hari berjalan dilewati, %s truk baru",
            batch_id, oleh, h.baru, nama_berkas, h.dari, h.sampai, h.sudah_ada,
            h.hari_berjalan, h.truk_dibuat,
        )
        return batch

    def _tulis(self, isi: bytes, batch_id: str, h: _Hitungan, hari_ini: str, hapus_ke: int) -> None:
        peta_truk = self._store.peta_truk_per_plat()
        supplier = self._store.supplier_per_nama()
        for potongan in self._potongan(isi, h, hari_ini):
            # Dicek sebelum tiap potongan: janjang yang ditulis sesudah Danger Zone
            # mulai menghapus akan tertinggal di pabrik yang baru dikosongkan.
            self._cek_hapus(hapus_ke)
            ada = self._store.event_sudah_ada([j.event_id for j in potongan])
            baru = [j for j in potongan if j.event_id not in ada]
            truk: list[dict[str, Any]] = []
            rows = [self._baris_db(j, peta_truk, supplier, truk) for j in baru]
            ditambah, truk_dibuat = self._store.simpan_potongan_impor(batch_id, rows, truk)
            h.truk_dibuat += truk_dibuat
            h.baru += ditambah
            h.sudah_ada += len(potongan) - ditambah
            for j in baru:
                h.catat_baru(j)

    def _baris_db(
        self,
        j: JanjangImpor,
        peta_truk: dict[str, str],
        supplier: dict[str, str | None],
        truk: list[dict[str, Any]],
    ) -> dict[str, Any]:
        truck_id = None
        if j.plat:
            kunci = normalisasi_plat(j.plat)
            truck_id = peta_truk.get(kunci)
            if truck_id is None:
                truck_id = peta_truk[kunci] = truck_id_for(j.plat)
                truk.append({
                    "id": truck_id,
                    "plate_number": j.plat,
                    "supplier_id": supplier.get((j.supplier or "").strip().lower()),
                })
        line = self._by_code.get(j.line_code)
        return {
            "event_id": j.event_id,
            # Line yang tidak dikenal disimpan dengan kodenya sebagai machine_id, sama
            # dengan ingest: barisnya tampil sebagai line asing, tidak hilang.
            "machine_id": line.machine_id if line else j.line_code,
            "line_code": j.line_code,
            "work_date": j.work_date,
            "timestamp": timestamp_utc(j.waktu, self._zona),
            "ripeness_status": j.ripeness_status,
            "ripeness_confidence": None,
            "capture_type": j.capture_type,
            "image_path": j.image_path,
            "truck_id": truck_id,
            "assignment_id": None,
            "received_at": self._jam(),
            "prediction": prediction_for(j.ripeness_status),
            "grade_class": j.grade_class,
            "tp_status": TP_PASS if j.tp else None,
            "tp_confidence": _TP_KEYAKINAN if j.tp else None,
        }

    def _selesai(self, batch_id: str, h: _Hitungan, *, status: str) -> None:
        self._store.selesai_impor(
            batch_id, status=status, finished_at=self._jam(), added=h.baru,
            skipped_existing=h.sudah_ada, skipped_today=h.hari_berjalan, duplicates=h.ganda,
            date_from=h.dari, date_to=h.sampai, new_trucks=h.truk_dibuat,
        )

    # --------------------------------------------------------------- daftar

    def daftar(self) -> dict[str, Any]:
        return {"items": self._store.daftar_impor()}

    # --------------------------------------------------------------- batal

    def batalkan(self, batch_id: str, *, oleh: str) -> dict[str, Any]:
        """Hapus semua janjang satu impor, per potongan. Truk yang dibuatnya tetap ada."""
        if not self._kunci.acquire(blocking=False):
            raise ImporDitolak(IMPOR_BERJALAN, "impor lain sedang berjalan")
        try:
            self._cek_hapus()
            batch = self._store.impor_grading(batch_id)
            if batch is None:
                raise ImporTidakAda(IMPOR_TIDAK_ADA, "impor tidak ditemukan")
            if batch["status"] == "undone":
                raise ImporDitolak(IMPOR_SUDAH_DIBATALKAN, "impor sudah dibatalkan")
            dihapus = 0
            while n := self._store.hapus_potongan_impor(batch_id, batas=self._potong_batal):
                dihapus += n
                self._jeda(_JEDA_BATAL_S)
            self._store.tandai_impor_dibatalkan(batch_id, oleh=oleh, now=self._jam(), removed=dihapus)
        finally:
            self._kunci.release()
        logger.warning(
            "Impor grading %s (%s) dibatalkan oleh %s: %s janjang dihapus",
            batch_id, batch["file_name"], oleh, dihapus,
        )
        return self._store.impor_grading(batch_id) or {}

    # ------------------------------------------------------------ bantuan

    def _potongan(self, isi: bytes, h: _Hitungan, hari_ini: str) -> Iterator[list[JanjangImpor]]:
        """Janjang yang bisa diimpor, per potongan; sisanya dihitung di `h`."""
        dilihat: set[str] = set()
        potongan: list[JanjangImpor] = []
        for item in baca(isi):
            h.baris += 1
            if isinstance(item, SalahBaris):
                h.salah += 1
                if len(h.contoh_salah) < _CONTOH_SALAH:
                    h.contoh_salah.append({"nomor": item.nomor, "kode": item.kode, "params": item.params})
                continue
            if item.event_id in dilihat:
                h.ganda += 1
                continue
            dilihat.add(item.event_id)
            if hari_berjalan(item, hari_ini):
                h.hari_berjalan += 1
                continue
            potongan.append(item)
            if len(potongan) >= self._potong:
                yield potongan
                potongan = []
        if potongan:
            yield potongan

    def _cek_hapus(self, hapus_ke: int | None = None) -> None:
        """Danger Zone sedang menghapus, atau sudah menghapus sejak `hapus_ke` dicatat."""
        berubah = hapus_ke is not None and self._store.jumlah_hapus != hapus_ke
        if self._store.hapus_berjalan or berubah:
            raise ImporDitolak(IMPOR_HAPUS_BERJALAN, "Danger Zone sedang menghapus data")


_sidik = sidik


def _cek_ukuran(isi: bytes) -> None:
    if len(isi) > MAKS_BYTE:
        raise InvalidInput(
            IMPOR_TERLALU_BESAR, "berkas terlalu besar", maks_mb=MAKS_BYTE // (1024 * 1024)
        )
