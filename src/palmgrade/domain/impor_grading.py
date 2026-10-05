"""Impor grading dari CSV Per janjang (tab Riwayat, khusus support), murni tanpa I/O.

Yang diterima cuma berkas yang dibuat konsol sendiri lewat **Unduh CSV → Per janjang**:
kepala kolomnya `KEPALA_CSV["janjang"]` (id atau en), sama persis dengan yang ditulis
ekspor. Ringkasan per hari / per truk tidak bisa diimpor (tidak ada janjangnya), dan
berkas yang disimpan ulang Excel ditolak: Excel mengganti pemisah, format tanggal, dan
membuang detik, jadi menebak isinya berarti mengarang data grading.

Baris yang salah TIDAK ditebak dan tidak dilewati diam-diam: tiap baris dilaporkan
dengan nomornya (nomor baris spreadsheet: kepala = 1) dan satu kode, supaya support
melihat masalahnya sebelum apa pun disimpan. Aturan hari (`hari_berjalan`) terpisah:
janjang hari ini masih berjalan dan ikut kunjungan truk yang dikirim ke AutoERP, jadi
impor tidak pernah menyentuhnya.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .grade_class import JK, UNRIPE, grade_class_of
from .operator_error import (
    IMPOR_BUKAN_JANJANG,
    IMPOR_BUKAN_UTF8,
    IMPOR_KOSONG,
    IMPOR_RUSAK,
    InvalidInput,
)
from .plate import normalisasi_plat
from .riwayat import JENIS_CAPTURE, KEPALA_CSV, TP_YA
from .vision_event import verdict_of

#: Batas ukuran berkas. Sebulan data pabrik yang sibuk muat; lebih dari itu diminta
#: dipecah per rentang tanggal, supaya satu unggahan tidak menahan memori konsol.
MAKS_BYTE = 50 * 1024 * 1024

#: Kode salah per baris. Layar menerjemahkan tiap kode lewat `imporSalah_<kode>` di
#: KAMUS kedua bahasa, dan test memeriksanya.
KODE_SALAH_BARIS = (
    "event_id_kosong", "event_id_tidak_sah", "tanggal_tidak_sah", "waktu_tidak_sah",
    "waktu_beda_tanggal", "line_kosong", "line_tidak_sah", "hasil_tidak_sah",
    "kelas_tidak_sah", "kelas_bertentangan", "tp_tidak_sah", "jenis_tidak_sah",
    "foto_tidak_sah", "plat_tidak_sah",
)

_NILAI_MAKS = 40
_FORMAT_WAKTU = "%Y-%m-%d %H:%M:%S"
# Kode line: `line-1`, atau machine_id untuk line yang tidak dikenal konsol asalnya.
# Ikut membentuk URL foto, jadi hurufnya dibatasi.
_POLA_LINE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
# Tanda yang membuat ekspor menambahkan `'` (`domain/riwayat.aman_untuk_csv`).
_AWALAN_RUMUS = ("=", "+", "-", "@", "\t", "\r")
_KOLOM = ("tanggal", "waktu", "line", "plat", "supplier", "sumber", "kelas", "hasil", "tp",
          "jenis", "foto", "event")
_TP_YA = {v.lower() for v in TP_YA.values()}
_JENIS = {nama.lower(): asli for bahasa in JENIS_CAPTURE.values() for asli, nama in bahasa.items()}


@dataclass(frozen=True)
class JanjangImpor:
    """Satu janjang yang sah, siap disimpan."""

    nomor: int
    event_id: str
    work_date: str
    #: Jam pabrik apa adanya dari berkas (`YYYY-MM-DD HH:MM:SS`).
    waktu: str
    line_code: str
    plat: str | None
    supplier: str | None
    grade_class: str | None
    ripeness_status: str
    tp: bool
    capture_type: str
    image_path: str | None


@dataclass(frozen=True)
class SalahBaris:
    nomor: int
    kode: str
    params: dict[str, str] = field(default_factory=dict)


class _Salah(Exception):
    def __init__(self, kode: str, **params: str) -> None:
        super().__init__(kode)
        self.kode = kode
        self.params = params


def sidik(isi: bytes) -> str:
    """Sidik isi berkas: impor hanya menyimpan berkas yang sama dengan yang diperiksa."""
    return hashlib.sha256(isi).hexdigest()


def hari_berjalan(janjang: JanjangImpor, hari_ini: str) -> bool:
    """Hari ini atau sesudahnya: tidak diimpor, datanya masih berjalan di pabrik."""
    return janjang.work_date >= hari_ini


def timestamp_utc(waktu: str, zona: ZoneInfo) -> str:
    """Jam pabrik di berkas → stempel UTC berbentuk sama dengan kiriman line."""
    lokal = datetime.strptime(waktu, _FORMAT_WAKTU).replace(tzinfo=zona)
    return lokal.astimezone(UTC).isoformat()


def baca(isi: bytes) -> Iterator[JanjangImpor | SalahBaris]:
    """Tiap baris data berkas, berurutan: janjang yang sah atau salahnya.

    Melempar `InvalidInput` untuk masalah berkas utuh (kosong, bukan UTF-8, bukan
    CSV Per janjang), sebelum baris data pertama dibaca.
    """
    try:
        teks = isi.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidInput(IMPOR_BUKAN_UTF8, "berkas bukan UTF-8") from None
    pembaca = csv.reader(io.StringIO(teks, newline=""))
    try:
        kepala = next(pembaca, None)
        if not kepala or not any(k.strip() for k in kepala):
            raise InvalidInput(IMPOR_KOSONG, "berkas kosong")
        posisi = _posisi_kolom([_asli(k) for k in kepala])
        for sel in pembaca:
            if not any(s.strip() for s in sel):
                continue
            nomor = pembaca.line_num
            try:
                yield _janjang(nomor, {nama: _sel(sel, i) for nama, i in posisi.items()})
            except _Salah as salah:
                yield SalahBaris(nomor, salah.kode, salah.params)
    except csv.Error as exc:
        # Tanda kutip yang tidak ditutup menelan sisa berkas jadi satu sel raksasa, NUL,
        # dan sejenisnya: struktur berkasnya rusak, bukan satu baris yang salah isi.
        raise InvalidInput(IMPOR_RUSAK, f"CSV rusak: {exc}", nomor=pembaca.line_num) from None


def _posisi_kolom(kepala: list[str]) -> dict[str, int]:
    bersih = [k.strip() for k in kepala]
    for bahasa in ("id", "en"):
        nama = KEPALA_CSV["janjang"][bahasa]
        if all(n in bersih for n in nama):
            return {kunci: bersih.index(n) for kunci, n in zip(_KOLOM, nama, strict=True)}
    for tampilan in ("hari", "truk"):
        if any(bersih == KEPALA_CSV[tampilan][b] for b in ("id", "en")):
            raise InvalidInput(IMPOR_BUKAN_JANJANG, "berkas ringkasan, bukan per janjang", jenis=tampilan)
    raise InvalidInput(IMPOR_BUKAN_JANJANG, "bukan CSV Per janjang", jenis="lain")


def _sel(sel: list[str], i: int) -> str:
    return _asli(sel[i]).strip() if i < len(sel) else ""


def _asli(nilai: str) -> str:
    """Lepas `'` yang dipasang ekspor di depan teks berawalan tanda rumus."""
    if len(nilai) > 1 and nilai[0] == "'" and nilai[1] in _AWALAN_RUMUS:
        return nilai[1:]
    return nilai


def _potong(nilai: str) -> str:
    return nilai[:_NILAI_MAKS]


def _janjang(nomor: int, sel: dict[str, str]) -> JanjangImpor:
    # Satu kode per baris, diperiksa dari identitasnya dulu: baris yang terpotong
    # di akhir unduhan dilaporkan "Event ID kosong", bukan kolom acak yang kebetulan
    # ikut hilang.
    event_id = _event_id(sel["event"])
    work_date = _tanggal(sel["tanggal"])
    waktu = _waktu(sel["waktu"], work_date)
    line_code = _line(sel["line"])
    ripeness_status = _hasil(sel["hasil"])
    return JanjangImpor(
        nomor=nomor,
        event_id=event_id,
        work_date=work_date,
        waktu=waktu,
        line_code=line_code,
        plat=_plat(sel["plat"]),
        supplier=sel["supplier"] or None,
        grade_class=_kelas(sel["kelas"], ripeness_status),
        ripeness_status=ripeness_status,
        tp=_tp(sel["tp"]),
        capture_type=_jenis(sel["jenis"]),
        image_path=_gambar(sel["foto"], line_code),
    )


def _event_id(nilai: str) -> str:
    if not nilai:
        raise _Salah("event_id_kosong")
    try:
        return str(uuid.UUID(nilai))
    except ValueError:
        raise _Salah("event_id_tidak_sah", nilai=_potong(nilai)) from None


def _tanggal(nilai: str) -> str:
    try:
        if len(nilai) != 10:
            raise ValueError(nilai)
        return date.fromisoformat(nilai).isoformat()
    except ValueError:
        raise _Salah("tanggal_tidak_sah", nilai=_potong(nilai)) from None


def _waktu(nilai: str, work_date: str) -> str:
    try:
        jam = datetime.strptime(nilai, _FORMAT_WAKTU)
    except ValueError:
        raise _Salah("waktu_tidak_sah", nilai=_potong(nilai)) from None
    # The working day is the date of `time - cutoff` (§6.1, batch 5.11), and a cutoff is under
    # 24 h: in a file the console made, the time falls on the working day itself or on the next
    # calendar day. Anything else means the file was edited.
    hari = date.fromisoformat(work_date)
    if jam.date() not in (hari, hari + timedelta(days=1)):
        raise _Salah("waktu_beda_tanggal", nilai=nilai, tanggal=work_date)
    return nilai


def _line(nilai: str) -> str:
    if not nilai:
        raise _Salah("line_kosong")
    if not _POLA_LINE.fullmatch(nilai):
        raise _Salah("line_tidak_sah", nilai=_potong(nilai))
    return nilai


def _plat(nilai: str) -> str | None:
    if not nilai:
        return None
    try:
        normalisasi_plat(nilai)
    except ValueError:
        raise _Salah("plat_tidak_sah", nilai=_potong(nilai)) from None
    # Plat ikut tersimpan apa adanya di tabel truk dan tampil di layar: karakter kontrol
    # (NUL, tab, ...) berarti berkasnya rusak, bukan plat.
    if len(nilai) > 32 or any(ord(c) < 32 for c in nilai):
        raise _Salah("plat_tidak_sah", nilai=_potong(nilai))
    return nilai


def _hasil(nilai: str) -> str:
    try:
        return verdict_of(nilai)
    except ValueError:
        raise _Salah("hasil_tidak_sah", nilai=_potong(nilai)) from None


def _kelas(nilai: str, ripeness_status: str) -> str | None:
    if not nilai:
        return None
    try:
        kelas = grade_class_of(nilai)
    except ValueError:
        raise _Salah("kelas_tidak_sah", nilai=_potong(nilai)) from None
    # Kelas TIDAK selalu menentukan verdict: line memaksa REJ untuk buah bertumpuk atau
    # terlalu kecil tanpa mengubah kelasnya, jadi Ripe + REJ sah dan ada tiap hari sibuk.
    # Yang tidak pernah ditulis line cuma kelas mentah yang diterima; berkas yang berkata
    # begitu sudah diubah, dan angka bayaran dijumlah dari verdict.
    if kelas in (UNRIPE, JK) and ripeness_status == "ACC":
        raise _Salah("kelas_bertentangan", kelas=kelas, hasil=ripeness_status)
    return kelas


def _tp(nilai: str) -> bool:
    if not nilai:
        return False
    if nilai.lower() in _TP_YA:
        return True
    raise _Salah("tp_tidak_sah", nilai=_potong(nilai))


def _jenis(nilai: str) -> str:
    # Kosong = "auto", sama dengan ingest (`ConsoleService.ingest`).
    if not nilai:
        return "auto"
    try:
        return _JENIS[nilai.lower()]
    except KeyError:
        raise _Salah("jenis_tidak_sah", nilai=_potong(nilai)) from None


def _gambar(nilai: str, line_code: str) -> str | None:
    """Kebalikan `_capture_url` di console_service: URL foto → `image_path`."""
    if not nilai:
        return None
    if nilai.lower().startswith(("http://", "https://")):
        return nilai
    awalan = f"/captures/{line_code}/"
    relatif = nilai[len(awalan):] if nilai.startswith(awalan) else ""
    bagian = relatif.split("/")
    if not relatif or ".." in bagian or "" in bagian or "\\" in relatif or any(ord(c) < 32 for c in relatif):
        raise _Salah("foto_tidak_sah", nilai=_potong(nilai))
    return "captures/" + relatif
