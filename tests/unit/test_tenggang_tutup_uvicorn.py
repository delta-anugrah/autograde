"""Urutan tutup line muat di tenggang `docker stop`, sesudah uvicorn menyerah (batch 2.2).

`docker stop` (dan `autograde restart`) mengirim SIGTERM lalu SIGKILL 10 detik
kemudian. uvicorn baru menjalankan lifespan shutdown, tempat `PenutupLine.tutup`
dipanggil, SESUDAH semua koneksi yang terbuka selesai. Layar konsol membuka
`/api/video_feed` tiap line terus-menerus, dan aliran MJPEG itu tidak pernah
selesai sendiri: tanpa `--timeout-graceful-shutdown` uvicorn menunggunya
selamanya, SIGKILL datang duluan, dan coil maupun antrean simpan tidak pernah
diurus (diukur 2026-09-29, uvicorn 0.34.0: masih hidup 15 detik sesudah SIGTERM).

Konsol sengaja TANPA batas itu: aliran tanpa ujungnya cuma ada di line, dan
satu-satunya `StreamingResponse` konsol (CSV Riwayat) selesai sendiri. Batas 1
detik di konsol cuma memotong permintaan yang sedang jalan saat `docker stop`:
CSV sebulan (~6 detik) dan hapus-data Danger Zone yang menunggu line mati
(sampai ~13 detik), yang tanpa batas masih sempat selesai.
"""
from __future__ import annotations

import re
from pathlib import Path

from palmgrade.services.penutup_line import BATAS_TUTUP_S

REPO = Path(__file__).resolve().parents[2]

#: Tenggang `docker stop` bawaan sebelum SIGKILL. Compose host pabrik tidak ikut
#: rilis, jadi `stop_grace_period` tidak bisa diandalkan untuk menambahnya.
TENGGANG_DOCKER_STOP_S = 10.0

#: Jeda uvicorn 0.34 di luar tenggang koneksi: satu tick loop utamanya (0,1
#: detik) + `asyncio.sleep(0.1)` di `Server.shutdown`. Diukur 0,12 detik.
OVERHEAD_UVICORN_S = 0.2

_TENGGANG = re.compile(r"--timeout-graceful-shutdown[ =]+(\d+(?:\.\d+)?)")


def _perintah_uvicorn(berkas: str) -> list[str]:
    """Tiap perintah yang menyalakan uvicorn untuk line atau konsol, baris lanjutan digabung."""
    teks = (REPO / berkas).read_text(encoding="utf-8").replace("\\\n", " ")
    return [
        baris for baris in teks.splitlines()
        if re.search(r"\buvicorn\b", baris) and not baris.lstrip().startswith("#")
    ]


def _tenggang(perintah: str) -> float:
    cocok = _TENGGANG.search(perintah)
    assert cocok, f"uvicorn line tanpa --timeout-graceful-shutdown: {perintah.strip()}"
    return float(cocok.group(1))


def _konsol(perintah: str) -> bool:
    return "console_main" in perintah


def test_image_line_menyerahkan_koneksi_terbuka_lalu_urutan_tutup_muat_sebelum_sigkill():
    line = [satu for satu in _perintah_uvicorn("entrypoint.sh") if not _konsol(satu)]
    assert len(line) == 2  # APP_ENV=development (--reload) dan produksi
    for satu in line:
        assert _tenggang(satu) + OVERHEAD_UVICORN_S + BATAS_TUTUP_S < TENGGANG_DOCKER_STOP_S, satu


def test_image_konsol_menunggu_permintaan_yang_sedang_jalan():
    konsol = [satu for satu in _perintah_uvicorn("entrypoint.sh") if _konsol(satu)]
    assert len(konsol) == 2  # APP_ENV=development (--reload) dan produksi
    for satu in konsol:
        assert not _TENGGANG.search(satu), satu


def test_jalur_native_makefile_sama_dengan_image():
    """`make line` dan `make dev` (line-1) memakai batas yang sama dengan image;
    `make console` tanpa batas, seperti konsol di image."""
    bawaan = {_tenggang(satu) for satu in _perintah_uvicorn("entrypoint.sh") if not _konsol(satu)}
    perintah = _perintah_uvicorn("Makefile")
    line = [satu for satu in perintah if not _konsol(satu)]
    konsol = [satu for satu in perintah if _konsol(satu)]
    assert len(line) >= 2 and len(konsol) >= 1
    assert {_tenggang(satu) for satu in line} == bawaan
    for satu in konsol:
        assert not _TENGGANG.search(satu), satu
