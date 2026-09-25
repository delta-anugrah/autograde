"""Hapus data SISI LINE untuk Danger Zone — berkas saja, tanpa torch, tanpa HTTP.

Konsol tidak bisa menghapus foto line: `artifacts/line-N` di-mount read-only ke
konsol. Jadi line yang menghapus datanya sendiri, dan melakukannya SAAT BOOT:

1. konsol memanggil `POST /internal/hapus-data` → line menulis penanda
   (`tulis_penanda`) di `artifacts/`-nya lalu keluar (`os._exit`,
   `restart: unless-stopped` yang menyalakannya lagi);
2. di awal lifespan, SEBELUM satu pun store atau worker membuka berkas,
   `hapus_kalau_diminta` melihat penanda itu dan mengosongkan `artifacts/`,
   ditambah berkas MILIK LINE di `state/`.

Penanda di `artifacts/`, bukan `state/`, dan `state/` cuma dihapus daftar milik
line: `artifacts/` selalu milik satu line (Docker `./artifacts/line-N`, native
`ARTIFACTS_DIR` per line), sedangkan di jalur native (`make line` + `make
console`) `state/` DIPAKAI BERSAMA konsol dan ketiga line. Menghapus seluruh
`state/` di situ menghapus basis data konsol yang sedang dibuka, dan penanda
bersama dimakan line pertama yang boot (temuan review 2026-09-25).

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

#: Nama berkas penanda di folder `artifacts/` line.
PENANDA = ".hapus-data"

#: Berkas MILIK LINE di `state/` (awalan: ikut `-wal`/`-shm`). Selain ini tidak
#: pernah disentuh — di jalur native folder itu juga berisi basis data konsol.
#: `test_semua_berkas_db_line_digolongkan` menjaga daftar ini lengkap.
MILIK_LINE_DI_STATE = ("upload_manifest.db",)

#: Awalan berkas di `artifacts/` yang selamat: `license.db` beserta `-wal`,
#: `-shm`, dan `-journal`-nya.
_AWALAN_SIMPAN = "license.db"

_AKHIRAN_REKAMAN = ".mp4"


def tulis_penanda(artifacts_dir: Path, *, mode: str, diminta_oleh: str, now: float) -> Path:
    """Tulis penanda secara atomik DAN tahan listrik mati.

    Atomik: ada utuh atau tidak ada sama sekali (tulis sementara + `os.replace`).
    Tahan listrik mati: isi dan entri foldernya di-fsync sebelum line keluar —
    konsol mengosongkan index-nya sesudah perintah ini, jadi penanda yang hilang
    saat listrik mati meninggalkan foto tanpa index.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    jalur = artifacts_dir / PENANDA
    sementara = artifacts_dir / f"{PENANDA}.tmp"
    with open(sementara, "w") as f:
        f.write(json.dumps({"mode": mode, "diminta_oleh": diminta_oleh, "diminta_pada": now}))
        f.flush()
        os.fsync(f.fileno())
    os.replace(sementara, jalur)
    try:
        fd = os.open(artifacts_dir, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass  # sebagian sistem berkas menolak fsync folder; isinya sudah aman
    return jalur


def hapus_diminta(artifacts_dir: Path) -> bool:
    """Ada perintah hapus yang menunggu boot berikutnya. Dipakai
    `/internal/assignment` untuk menolak truk baru di detik sebelum line keluar."""
    return (artifacts_dir / PENANDA).exists()


def hapus_kalau_diminta(artifacts_dir: Path, state_dir: Path) -> dict[str, Any] | None:
    """Kosongkan data line ini kalau ada penanda di `artifacts/`. `None` kalau tidak ada.

    `dihapus` = jumlah item tingkat atas yang hilang (folder dihitung satu).

    Penanda dihapus PALING AKHIR, dan hanya kalau semuanya berhasil: boot yang
    terputus di tengah (listrik mati) atau berkas yang menolak dihapus membuat
    boot berikutnya mengulang, bukan meninggalkan separuh data tanpa jejak.
    """
    penanda = artifacts_dir / PENANDA
    if not penanda.exists():
        return None
    info = _baca_penanda(penanda)
    # Dicatat SEBELUM mulai: berbulan-bulan foto bisa makan menit, dan selama
    # itu line belum mendengarkan port-nya — terbaca mati di konsol.
    logger.warning(
        "Penanda hapus data ditemukan — mulai menghapus data line ini (mode %s, diminta %s). "
        "Bisa beberapa menit kalau fotonya banyak.", info["mode"], info["diminta_oleh"],
    )
    dihapus = gagal = 0
    for anak in _isi(artifacts_dir):
        if anak.name.startswith(_AWALAN_SIMPAN) or anak.name in (PENANDA, f"{PENANDA}.tmp"):
            continue
        ok = _hapus(anak)
        dihapus += 1 if ok else 0
        gagal += 0 if ok else 1
    for anak in _isi(state_dir):
        if not anak.name.startswith(MILIK_LINE_DI_STATE):
            continue
        ok = _hapus(anak)
        dihapus += 1 if ok else 0
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


def _hapus(jalur: Path) -> bool:
    """Hapus satu anak folder (berkas, atau folder beserta isinya) dalam SATU
    lintasan. Tidak menghitung berkas di dalamnya: itu berarti menyisir pohon
    foto dua kali, dan berbulan-bulan foto = menit tambahan saat line mati."""
    try:
        if jalur.is_dir() and not jalur.is_symlink():
            shutil.rmtree(jalur)
        else:
            jalur.unlink()
        return True
    except OSError as exc:
        logger.warning("Tidak bisa menghapus %s: %s", jalur, exc)
        return False


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
