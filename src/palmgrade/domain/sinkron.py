"""Last Sync: status sambungan konsol ke AutoERP dan Cloud Photo (R2), murni tanpa I/O.

Layar operator punya satu bagian **Last Sync** berisi dua baris, AutoERP dan Cloud
Photo (permintaan user 2026-09-27). Tiap baris menjawab dua hal yang sengaja dipisah:

- `terakhir`: kapan data terakhir benar-benar tersinkron;
- `keadaan`: apakah sambungannya hidup SEKARANG.

Foto naik ke R2 tiap jam, jadi "terakhir 13:05" pada jam 13:50 itu normal, bukan tanda
putus. Warna ditentukan hasil percobaan terakhir (kiriman atau cek tiap menit), bukan
umur `terakhir`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

TERSAMBUNG = "tersambung"
TERPUTUS = "terputus"
TIDAK_DIPAKAI = "tidak_dipakai"
MEMERIKSA = "memeriksa"

#: Sumber khusus untuk galat jaringan (tanpa jawaban, atau gateway mati). Jawaban apa
#: pun dari server, lewat sumber mana saja, membersihkannya: jaringannya jelas hidup.
SUMBER_JARINGAN = "jaringan"

_PESAN_MAKS = 200
_GATEWAY_MATI = (502, 503, 504)


@dataclass
class Jejak:
    """Fakta satu sumber sambungan (cek, tarik, kirim, ...): kapan terakhir berhasil,
    sejak kapan gagal terus, dan alasan gagal terakhir."""

    ok_at: float | None = None
    gagal_sejak: float | None = None
    pesan: str | None = None

    def berhasil(self, now: float) -> bool:
        """Catat kontak yang berhasil. True kalau ini menyudahi deretan gagal."""
        pulih = self.gagal_sejak is not None
        self.ok_at = now
        self.gagal_sejak = None
        self.pesan = None
        return pulih

    def gagal(self, now: float, pesan: str) -> bool:
        """Catat kegagalan. True kalau ini AWAL deretan gagal (baru saja putus).

        `gagal_sejak` tidak digeser oleh kegagalan berikutnya: layar menulis
        "terputus sejak 13:40", bukan jam percobaan terakhir.
        """
        mulai = self.gagal_sejak is None
        if mulai:
            self.gagal_sejak = now
        self.pesan = " ".join(str(pesan).split())[:_PESAN_MAKS] or None
        return mulai


def galat_jaringan_http(status: int | None) -> bool:
    """Galat yang berarti jaringan/gateway, bukan penolakan dari server.

    `None` = tidak ada jawaban HTTP sama sekali (putus, timeout). 502/503/504 = gateway
    di depan server tidak bisa meneruskan. Sisanya (401, 403, 404, 417, 500, ...)
    berarti server MENJAWAB.
    """
    return status is None or status in _GATEWAY_MATI


def awal_gagal(jejak: Iterable[Jejak]) -> float | None:
    """Awal kegagalan yang sedang berlangsung, dari sumber mana pun."""
    sejak = [j.gagal_sejak for j in jejak if j.gagal_sejak is not None]
    return min(sejak) if sejak else None


def keadaan(jejak: Iterable[Jejak], *, aktif: bool) -> str:
    """Satu sambungan dari semua sumbernya: putus kalau SATU sumber sedang gagal.

    Tiap sumber pulih sendiri. Cek tiap menit yang lolos tidak menghapus tarikan data
    yang ditolak; tanpa aturan ini dua sumber yang menilai beda membuat titik di layar
    berkedip merah-hijau dan mengisi tab Log.
    """
    daftar = list(jejak)
    if not aktif:
        return TIDAK_DIPAKAI
    if awal_gagal(daftar) is not None:
        return TERPUTUS
    if not any(j.ok_at is not None for j in daftar):
        return MEMERIKSA
    return TERSAMBUNG


def ringkas(
    jejak: Iterable[Jejak], *, aktif: bool, antre: int, terakhir: float | None
) -> dict[str, Any]:
    """Bentuk satu baris Last Sync untuk layar. `terakhir` dicatat pemanggil, hanya
    saat data benar-benar lewat."""
    daftar = list(jejak)
    return {
        "keadaan": keadaan(daftar, aktif=aktif),
        "terakhir": terakhir,
        "sejak": awal_gagal(daftar) if aktif else None,
        "antre": antre,
    }


def unggah_dari_state(state: Any) -> dict[str, Any] | None:
    """Blok `unggah` untuk `/internal/status` line: ringkasan upload foto terakhir.

    `RuntimeState.status_unggah` dipasang `main.py` begitu `BatchUploadWorker` ada;
    None sebelum itu (line baru menyala) dan di proses yang tidak mengunggah.
    """
    baca = getattr(state, "status_unggah", None)
    return baca() if callable(baca) else None


def _angka(nilai: Any) -> float | None:
    """Angka dari laporan line, atau None. Line versi kelak bisa mengirim bentuk lain,
    dan polling layar 2 detik tidak boleh ikut mati karenanya."""
    if isinstance(nilai, bool) or not isinstance(nilai, int | float):
        return None
    return float(nilai)


def gabung_cloud(konsol: dict[str, Any], lines: dict[str, Any]) -> dict[str, Any]:
    """Cloud Photo = cek R2 dari konsol (plus manifest kunjungan) + unggahan foto tiap line.

    `konsol` adalah `ringkas()` milik konsol. `lines` memetakan kode line ke blok
    `unggah` dari `/internal/status`-nya, atau None kalau line tidak terbaca atau
    versinya belum mengirim blok itu. Line mati TIDAK membuat Cloud Photo merah:
    kartunya sendiri sudah menulis OFFLINE, dan baris ini bicara soal cloud.

    Jam `terakhir` = yang paling baru; satu sumber yang gagal cukup membuat status
    terputus, sejak kegagalan yang paling awal. Selama konsol belum sempat mengecek R2
    (baru menyala), jam R2 yang tersimpan tidak dihitung sebagai bukti hidup: hijau baru
    kalau ada line yang melaporkan upload.
    """
    per_line: list[dict[str, Any]] = []
    jam_line: list[float] = []
    sejak = [konsol["sejak"]] if konsol.get("keadaan") == TERPUTUS and konsol.get("sejak") else []
    antre = int(_angka(konsol.get("antre")) or 0)
    ada_line_aktif = False
    for kode, unggah in sorted(lines.items()):
        if not isinstance(unggah, dict) or not unggah:
            per_line.append({"line_code": kode, "terbaca": False})
            continue
        aktif = bool(unggah.get("aktif"))
        terakhir = _angka(unggah.get("terakhir"))
        gagal_sejak = _angka(unggah.get("gagal_sejak"))
        antre_line = int(_angka(unggah.get("antre")) or 0)
        per_line.append({
            "line_code": kode,
            "terbaca": True,
            "aktif": aktif,
            "terakhir": terakhir,
            "sejak": gagal_sejak,
            "antre": antre_line,
        })
        if not aktif:
            continue
        ada_line_aktif = True
        antre += antre_line
        if terakhir:
            jam_line.append(terakhir)
        if gagal_sejak:
            sejak.append(gagal_sejak)

    jam_ada = [j for j in (_angka(konsol.get("terakhir")), *jam_line) if j]
    if konsol.get("keadaan") == TIDAK_DIPAKAI and not ada_line_aktif:
        hasil = TIDAK_DIPAKAI
    elif sejak:
        hasil = TERPUTUS
    elif konsol.get("keadaan") == MEMERIKSA and not jam_line:
        hasil = MEMERIKSA
    else:
        hasil = TERSAMBUNG
    return {
        "keadaan": hasil,
        "terakhir": max(jam_ada) if jam_ada else None,
        "sejak": min(sejak) if sejak else None,
        "antre": antre,
        "per_line": per_line,
    }
