"""Aturan Danger Zone (layar Setelan, support saja) — murni, tanpa I/O.

Yang diputuskan di sini: kapan menghapus data pabrik DITOLAK (hambatan), apa
yang cukup diperingatkan, dan tabel mana yang dihapus per mode. Layar memakai
hasil yang sama untuk menjelaskan, server untuk menolak — dua tempat, satu
aturan, jadi keduanya tidak bisa berbeda diam-diam.

Rancangan: `docs/superpowers/specs/2026-09-25-danger-zone-design.md`.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Kata yang harus diketik untuk aksi hapus. Diketik, bukan diklik: layar sentuh
#: bisa mendaftarkan sentuhan tak sengaja sebagai klik, tapi tidak ada yang
#: mengetik satu kata tertentu tanpa maksud. Sama dengan `autograde reset-data-fresh`.
KONFIRMASI_HAPUS = "HAPUS"

MODE_TRANSAKSI = "transaksi"
MODE_SEMUA = "semua"
MODE_HAPUS = (MODE_TRANSAKSI, MODE_SEMUA)

# Golongan tabel console.db.
_TRANSAKSI = "transaksi"  # dihapus di kedua mode
_SEMUA = "semua"  # dihapus di mode semua saja
_SEBAGIAN = "sebagian"  # tidak pernah dikosongkan utuh; dipilah per kunci

#: Tiap tabel `console.db` dan golongannya. `test_semua_tabel_konsol_digolongkan`
#: membandingkannya dengan `sqlite_master`: tabel baru membuat test merah sampai
#: ada yang memutuskan golongannya dengan sadar.
GOLONGAN_TABEL_KONSOL: dict[str, str] = {
    "inspections": _TRANSAKSI,
    "assignments": _TRANSAKSI,
    "auto_releases": _TRANSAKSI,
    "weighings": _TRANSAKSI,
    "trucks": _SEMUA,
    "suppliers": _SEMUA,
    "operators": _SEMUA,
    "sesi": _SEMUA,
    # Setelan grading & rekam hidup di sini, bersama kursor tarik AutoERP.
    "sync_state": _SEBAGIAN,
}

#: Kunci `sync_state` yang tidak pernah dihapus: setelan grading, garis capture,
#: dan rekam. Kembali ke nilai `.env` diam-diam = angka yang dibayar berubah
#: tanpa ada yang sadar.
_AWALAN_SETELAN = "setelan_"
#: Kursor tarik AutoERP. Ikut dihapus hanya kalau datanya (truk, supplier,
#: akun) juga dihapus — itu yang membuat tarikan berikutnya mengambil semuanya.
_AWALAN_KURSOR_ERP = "erp_cursor_"


@dataclass(frozen=True)
class KeadaanLine:
    """Apa yang konsol tahu tentang satu line saat panel dibuka / tombol ditekan.

    `outbox_pending=None` pada line yang menjawab berarti TIDAK DIKETAHUI, bukan
    nol — dan diperlakukan sebagai belum kosong.
    """

    line_code: str
    terjangkau: bool
    truk_terpasang: bool = False
    outbox_pending: int | None = None
    merekam: bool = False
    rekaman_berkas: int = 0
    rekaman_bytes: int = 0


@dataclass(frozen=True)
class KeadaanKonsol:
    erp_aktif: bool
    erp_pending: int = 0
    erp_gagal: int = 0
    #: Ada hash akun bawaan (`CONSOLE_DEFAULT_HASH`/`CONSOLE_SUPPORT_HASH`) yang
    #: bisa dibuat ulang sesudah mode semua menghapus seluruh akun.
    akun_bawaan: bool = True


def konfirmasi_sah(teks: str | None) -> bool:
    """Persis `HAPUS`; spasi di tepi dibuang, huruf besar-kecil dibedakan."""
    return (teks or "").strip() == KONFIRMASI_HAPUS


def hambatan_hapus_data(lines: list[KeadaanLine], konsol: KeadaanKonsol) -> list[dict]:
    """Alasan menghapus data DITOLAK. Kosong = boleh.

    Satu sebab per line, yang paling mendasar dulu: line mati sudah cukup
    alasannya, menyebut antreannya juga cuma menambah baris merah.
    """
    if not lines:
        # Konsol tanpa line tidak bisa menyuruh siapa pun menghapus foto;
        # mengosongkan index-nya saja meninggalkan foto yatim di disk.
        return [{"kode": "tanpa_line"}]
    hambatan: list[dict] = []
    for line in lines:
        if not line.terjangkau:
            hambatan.append({"kode": "line_mati", "line": line.line_code})
        elif line.truk_terpasang:
            hambatan.append({"kode": "truk_terpasang", "line": line.line_code})
        elif line.outbox_pending is None or line.outbox_pending > 0:
            item = {"kode": "antrean_line", "line": line.line_code}
            if line.outbox_pending is not None:
                item["jumlah"] = line.outbox_pending
            hambatan.append(item)
    # Kunjungan yang belum sampai ke AutoERP akan hilang dari buku. Tanpa
    # ERP_URL antrean itu memang tidak akan pernah terkirim — menghambat berarti
    # tombolnya tidak bisa dipakai selamanya, jadi cukup diperingatkan.
    if konsol.erp_aktif and konsol.erp_pending > 0:
        hambatan.append({"kode": "antrean_erp", "jumlah": konsol.erp_pending})
    return hambatan


def hambatan_mode_semua(konsol: KeadaanKonsol) -> list[dict]:
    """Tambahan khusus mode semua, yang menghapus SELURUH akun.

    Sesudahnya yang bisa masuk cuma akun bawaan (dibuat ulang dari hash di
    `.env`) dan akun AutoERP (turun lewat tarikan). Tanpa keduanya konsol
    terkunci sampai teknisi datang membawa terminal.
    """
    if not konsol.akun_bawaan and not konsol.erp_aktif:
        return [{"kode": "tanpa_sumber_akun"}]
    return []


def peringatan_hapus_data(
    lines: list[KeadaanLine], konsol: KeadaanKonsol, mode: str
) -> list[dict]:
    """Yang boleh lanjut, tapi harus dibaca dulu."""
    # Tanpa angka, sengaja: foto baru belum masuk manifest upload sampai tick jam
    # berikutnya, jadi angka dari manifest terbaca "0" padahal belum.
    peringatan: list[dict] = [{"kode": "foto_belum_r2"}]
    if konsol.erp_aktif and konsol.erp_gagal > 0:
        peringatan.append({"kode": "kiriman_gagal", "jumlah": konsol.erp_gagal})
    tertahan = konsol.erp_pending + konsol.erp_gagal
    if not konsol.erp_aktif and tertahan > 0:
        peringatan.append({"kode": "erp_mati", "jumlah": tertahan})
    if mode == MODE_SEMUA:
        peringatan.append({"kode": "semua_keluar"})
    return peringatan


def peringatan_restart(lines: list[KeadaanLine]) -> list[dict]:
    """Restart tidak pernah diblokir (keputusan yang sama dengan Model Deteksi),
    tapi yang akan terganggu disebut."""
    peringatan: list[dict] = []
    for line in lines:
        if not line.terjangkau:
            peringatan.append({"kode": "line_mati", "line": line.line_code})
            continue
        if line.truk_terpasang:
            peringatan.append({"kode": "truk_terpasang", "line": line.line_code})
        if line.merekam:
            peringatan.append({"kode": "line_merekam", "line": line.line_code})
    return peringatan


def peringatan_hapus_rekaman(lines: list[KeadaanLine]) -> list[dict]:
    """Line yang sedang merekam menolak (berkasnya sedang ditulis) dan line yang
    tidak menjawab dilewati — rekaman milik keduanya tetap ada."""
    peringatan: list[dict] = []
    for line in lines:
        if not line.terjangkau:
            peringatan.append({"kode": "line_mati", "line": line.line_code})
        elif line.merekam:
            peringatan.append({"kode": "line_merekam", "line": line.line_code})
    return peringatan


def _mode_sah(mode: str) -> str:
    if mode not in MODE_HAPUS:
        raise ValueError(f"mode hapus tidak dikenal: {mode!r}")
    return mode


def tabel_dihapus(mode: str) -> tuple[str, ...]:
    """Tabel console.db yang dikosongkan UTUH pada mode ini."""
    _mode_sah(mode)
    golongan = {_TRANSAKSI} if mode == MODE_TRANSAKSI else {_TRANSAKSI, _SEMUA}
    return tuple(t for t, g in GOLONGAN_TABEL_KONSOL.items() if g in golongan)


def kunci_state_dihapus(kunci: str, mode: str) -> bool:
    """Apakah satu baris `sync_state` ikut dihapus pada mode ini."""
    _mode_sah(mode)
    if kunci.startswith(_AWALAN_SETELAN):
        return False
    if kunci.startswith(_AWALAN_KURSOR_ERP):
        return mode == MODE_SEMUA
    return True
