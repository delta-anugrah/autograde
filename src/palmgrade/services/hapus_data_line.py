"""Hapus data SISI LINE untuk Danger Zone — berkas saja, tanpa torch, tanpa HTTP.

Konsol tidak bisa menghapus foto line: `artifacts/line-N` di-mount read-only ke
konsol. Jadi line yang menghapus datanya sendiri, dan melakukannya SAAT BOOT:

1. konsol memanggil `POST /internal/hapus-data` → line menulis penanda
   (`tulis_penanda`) lalu keluar (`os._exit`, `restart: unless-stopped` yang
   menyalakannya lagi);
2. di awal lifespan, SEBELUM satu pun store atau worker membuka berkas,
   `hapus_kalau_diminta` melihat penanda itu dan mengosongkan `artifacts/` dan
   `state/`.

Kenapa saat boot: SQLite yang sedang dibuka tidak boleh dihapus dari bawah
proses yang memakainya — proses itu tetap menulis ke berkas yang sudah
di-unlink, dan layar terus menampilkan data lama sampai restart.

`license.db*` (di `artifacts/`) TIDAK pernah dihapus: itu penjaga jam lisensi,
bukan data transaksi. Menghapusnya membuat jam PC bisa dimundurkan untuk
memperpanjang langganan. `autograde reset-data-fresh` di terminal memang
menghapusnya; tombol di konsol sengaja tidak.

Rancangan: `docs/superpowers/specs/2026-09-25-danger-zone-design.md` §5.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Nama berkas penanda di folder `state/` line.
PENANDA = ".hapus-data"

#: Awalan berkas di `artifacts/` yang selamat: `license.db` beserta `-wal`,
#: `-shm`, dan `-journal`-nya.
_AWALAN_SIMPAN = "license.db"

_AKHIRAN_REKAMAN = ".mp4"


def tulis_penanda(state_dir: Path, *, mode: str, diminta_oleh: str, now: float) -> Path:
    """Tulis penanda secara atomik: ada utuh, atau tidak ada sama sekali."""
    state_dir.mkdir(parents=True, exist_ok=True)
    jalur = state_dir / PENANDA
    sementara = state_dir / f"{PENANDA}.tmp"
    sementara.write_text(
        json.dumps({"mode": mode, "diminta_oleh": diminta_oleh, "diminta_pada": now})
    )
    os.replace(sementara, jalur)
    return jalur


def hapus_kalau_diminta(artifacts_dir: Path, state_dir: Path) -> dict[str, Any] | None:
    """Kosongkan data line ini kalau ada penanda. `None` kalau tidak ada.

    Penanda dihapus PALING AKHIR, dan hanya kalau semuanya berhasil: boot yang
    terputus di tengah (listrik mati) atau berkas yang menolak dihapus membuat
    boot berikutnya mengulang, bukan meninggalkan separuh data tanpa jejak.
    """
    penanda = state_dir / PENANDA
    if not penanda.exists():
        return None
    info = _baca_penanda(penanda)
    dihapus = gagal = 0
    for anak in _isi(artifacts_dir):
        if anak.name.startswith(_AWALAN_SIMPAN):
            continue
        ok, n = _hapus(anak)
        dihapus += n
        gagal += 0 if ok else 1
    for anak in _isi(state_dir):
        if anak.name in (PENANDA, f"{PENANDA}.tmp"):
            continue
        ok, n = _hapus(anak)
        dihapus += n
        gagal += 0 if ok else 1
    if gagal == 0:
        penanda.unlink(missing_ok=True)
    else:
        logger.error(
            "Hapus data line belum tuntas: %d item gagal dihapus — penanda dibiarkan, "
            "boot berikutnya mencoba lagi", gagal,
        )
    return {**info, "dihapus": dihapus, "gagal": gagal}


def ringkas_rekaman(rekaman_dir: Path, line_code: str) -> dict[str, int]:
    """Jumlah dan ukuran rekaman MILIK line ini."""
    berkas = _rekaman_milik(rekaman_dir, line_code)
    return {"berkas": len(berkas), "bytes": sum(_ukuran(p) for p in berkas)}


def hapus_rekaman(rekaman_dir: Path, line_code: str) -> dict[str, int]:
    """Hapus rekaman MILIK line ini saja.

    Folder `videos/` dipakai bersama tiga line, jadi tiap line menghapus miliknya
    sendiri berdasarkan nama yang ditulis `VideoRecorder`
    (`{line_code}_{stempel}.mp4`). Garis bawahnya bagian dari pola: tanpa itu
    `line-1` ikut menghapus rekaman `line-10`.
    """
    jumlah = total = 0
    for jalur in _rekaman_milik(rekaman_dir, line_code):
        ukuran = _ukuran(jalur)
        try:
            jalur.unlink()
        except OSError as exc:
            logger.warning("Rekaman %s tidak bisa dihapus: %s", jalur.name, exc)
            continue
        jumlah += 1
        total += ukuran
    return {"berkas": jumlah, "bytes": total}


# ── privat ──────────────────────────────────────────────────────────────────


def _baca_penanda(penanda: Path) -> dict[str, Any]:
    """Isi penanda; yang rusak tetap berarti "hapus" — keberadaannya perintahnya."""
    try:
        isi = json.loads(penanda.read_text())
        return {"mode": str(isi.get("mode", "?")), "diminta_oleh": str(isi.get("diminta_oleh", "?"))}
    except (OSError, ValueError, AttributeError):
        return {"mode": "?", "diminta_oleh": "?"}


def _isi(folder: Path) -> list[Path]:
    try:
        return sorted(folder.iterdir())
    except FileNotFoundError:
        return []


def _hapus(jalur: Path) -> tuple[bool, int]:
    """Hapus satu anak folder. Kembalikan (berhasil, jumlah berkas yang hilang)."""
    try:
        if jalur.is_dir() and not jalur.is_symlink():
            n = sum(1 for p in jalur.rglob("*") if not p.is_dir())
            shutil.rmtree(jalur)
            return True, n
        jalur.unlink()
        return True, 1
    except OSError as exc:
        logger.warning("Tidak bisa menghapus %s: %s", jalur, exc)
        return False, 0


def _rekaman_milik(rekaman_dir: Path, line_code: str) -> list[Path]:
    if not line_code or any(c in line_code for c in "/\\") or ".." in line_code:
        raise ValueError(f"kode line tidak sah untuk pola rekaman: {line_code!r}")
    awalan = f"{line_code}_"
    return [
        p
        for p in _isi(rekaman_dir)
        if p.is_file() and p.name.startswith(awalan) and p.name.endswith(_AKHIRAN_REKAMAN)
    ]


def _ukuran(jalur: Path) -> int:
    try:
        return jalur.stat().st_size
    except OSError:
        return 0
