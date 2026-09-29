"""Urutan tutup line muat di tenggang `docker stop`, sesudah uvicorn menyerah (batch 2.2).

`docker stop` (dan `autograde restart`) mengirim SIGTERM lalu SIGKILL 10 detik
kemudian. uvicorn baru menjalankan lifespan shutdown, tempat `PenutupLine.tutup`
dipanggil, SESUDAH semua koneksi yang terbuka selesai. Layar konsol membuka
`/api/video_feed` tiap line terus-menerus, dan aliran MJPEG itu tidak pernah
selesai sendiri: tanpa `--timeout-graceful-shutdown` uvicorn menunggunya
selamanya, SIGKILL datang duluan, dan coil maupun antrean simpan tidak pernah
diurus (diukur 2026-09-29, uvicorn 0.34.0: masih hidup 15 detik sesudah SIGTERM).
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
    assert cocok, f"uvicorn tanpa --timeout-graceful-shutdown: {perintah.strip()}"
    return float(cocok.group(1))


def test_image_menyerahkan_koneksi_terbuka_lalu_urutan_tutup_muat_sebelum_sigkill():
    perintah = _perintah_uvicorn("entrypoint.sh")
    assert len(perintah) == 2  # APP_ENV=development (--reload) dan produksi
    for satu in perintah:
        assert _tenggang(satu) + OVERHEAD_UVICORN_S + BATAS_TUTUP_S < TENGGANG_DOCKER_STOP_S, satu


def test_jalur_native_makefile_memakai_tenggang_yang_sama():
    """`make line`, `make dev`, dan `make console` berperilaku seperti image:
    Ctrl+C dengan layar konsol terbuka tidak boleh menggantung di sini saja."""
    bawaan = {_tenggang(satu) for satu in _perintah_uvicorn("entrypoint.sh")}
    perintah = _perintah_uvicorn("Makefile")
    assert len(perintah) >= 3
    assert {_tenggang(satu) for satu in perintah} == bawaan
