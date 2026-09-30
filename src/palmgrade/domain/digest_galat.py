"""Ringkasan galat penting untuk Discord (batch 3.5, F2 di TODO): kelompok, isi pesan, redaksi.

Murni, tanpa I/O. Satu ringkasan = semua ERROR yang menumpuk sejak ringkasan terakhir,
dikelompokkan per jenis (pesan yang angka dan id-nya dinormalkan lewat `normalkan_pesan`,
satu normaliser yang sama dipakai penggabungan tab Log dan antrean log line), dengan
hitungan, jam pertama dan terakhir, identitas pabrik, dan versi. Traceback TIDAK ikut: yang
keluar pabrik cuma cukup untuk tahu ada apa, rinciannya tetap di tab Log konsol.

Batas Discord: 2000 karakter per pesan. Ringkasan panjang dipecah jadi beberapa pesan
bernomor, paling banyak `MAKS_PESAN`; jenis yang tidak muat disebut jumlahnya.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .log_redaksi import redact
from .sidik_log import normalkan_pesan

BATAS_KARAKTER_DISCORD = 2000
MAKS_PESAN = 5
MAKS_KELOMPOK = 40
PANJANG_PESAN_GALAT = 300
#: Jenis galat berbeda yang ditampung antrean sebelum sisanya dilebur ke satu kelompok
#: "galat lain": pesan yang tidak bisa dinormalkan tidak boleh menumbuhkan berkas tanpa batas.
BATAS_KELOMPOK_MENUNGGU = 500
SIDIK_LAIN = "lain"
PESAN_LAIN = "galat lain (jenis terlalu banyak untuk dirinci)"

_WEBHOOK = re.compile(r"https?://(?:[a-z]+\.)?discord(?:app)?\.com/api/webhooks/\S+", re.I)
_MASK = "«redacted»"


@dataclass(frozen=True)
class KelompokGalat:
    level: str
    source: str
    line_code: str | None
    message: str
    pertama_at: float
    terakhir_at: float
    jumlah: int


def sidik_digest(level: str, source: str, line_code: str | None, message: str) -> str:
    kunci = f"{level}|{source}|{line_code or ''}|{normalkan_pesan(message)}"
    return hashlib.sha256(kunci.encode()).hexdigest()[:32]


def redaksi_discord(teks: str) -> str:
    """`redact` repo + alamat webhook Discord sendiri, yang bukan pola `kunci=nilai`."""
    return _WEBHOOK.sub(_MASK, redact(teks))


def identitas_pabrik(erp_company: str, host: str) -> str:
    """Nama pabrik untuk judul ringkasan: Company AutoERP, dan host PC sebagai pembeda."""
    nama = erp_company.strip() or "ERP_COMPANY belum diisi"
    return f"{nama} (host {host})" if host else nama


def _jam(ts: float, zona: ZoneInfo, acuan: datetime) -> str:
    d = datetime.fromtimestamp(ts, zona)
    return d.strftime("%H:%M") if d.date() == acuan.date() else d.strftime("%d/%m %H:%M")


def _bersih(pesan: str) -> str:
    satu_baris = " ".join(redaksi_discord(pesan).split()).replace("`", "'")
    if len(satu_baris) > PANJANG_PESAN_GALAT:
        satu_baris = satu_baris[: PANJANG_PESAN_GALAT - 3] + "..."
    return satu_baris


def _baris(k: KelompokGalat, zona: ZoneInfo, acuan: datetime) -> str:
    asal = k.line_code or "konsol"
    waktu = _jam(k.pertama_at, zona, acuan)
    if int(k.terakhir_at // 60) != int(k.pertama_at // 60):
        waktu += f" sampai {_jam(k.terakhir_at, zona, acuan)}"
    return f"- {k.jumlah}x {asal} · {k.source}: `{_bersih(k.message)}` ({waktu})"


def _kemas(baris: list[str], batas: int) -> list[str]:
    bagian: list[str] = []
    kini = ""
    for b in baris:
        calon = f"{kini}\n{b}" if kini else b
        if len(calon) > batas and kini:
            bagian.append(kini)
            kini = b
        else:
            kini = calon
    if kini:
        bagian.append(kini)
    return bagian


def susun_pesan(
    kelompok: list[KelompokGalat],
    *,
    identitas: str,
    versi: str,
    zona: ZoneInfo,
    batas: int = BATAS_KARAKTER_DISCORD,
    maks_pesan: int = MAKS_PESAN,
    maks_kelompok: int = MAKS_KELOMPOK,
) -> list[str]:
    """Isi pesan Discord untuk satu ringkasan. Kosong kalau tidak ada kelompok."""
    if not kelompok:
        return []
    urut = sorted(kelompok, key=lambda k: (-k.jumlah, -k.terakhir_at))
    acuan = datetime.fromtimestamp(max(k.terakhir_at for k in urut), zona)
    total = sum(k.jumlah for k in urut)
    dari = min(k.pertama_at for k in urut)
    kepala = [
        f"**AutoGrade {redaksi_discord(identitas)}** · versi {versi}",
        f"Ringkasan galat: {total} kejadian, {len(urut)} jenis, "
        f"{_jam(dari, zona, acuan)} sampai {acuan.strftime('%H:%M')} {acuan.tzname()}.",
    ]
    ekor = "Rincian dan traceback: konsol, tab Log."
    tampil = min(len(urut), maks_kelompok)
    ruang = batas - len("(99/99)\n")
    while True:
        isi = [_baris(k, zona, acuan) for k in urut[:tampil]]
        sisa = len(urut) - tampil
        penutup = ([f"...dan {sisa} jenis galat lain."] if sisa else []) + [ekor]
        bagian = _kemas(kepala + isi + penutup, ruang)
        if len(bagian) <= maks_pesan or tampil == 0:
            break
        tampil -= 1
    if len(bagian) == 1:
        return bagian
    return [f"({i}/{len(bagian)})\n{b}" for i, b in enumerate(bagian, 1)]
