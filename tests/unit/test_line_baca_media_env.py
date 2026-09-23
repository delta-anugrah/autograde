"""Line membaca `media.env` sendiri, bukan hanya environment container.

Kenapa ini ada: environment sebuah container BEKU sejak container dibuat.
Tombol "Simpan & Restart" di layar Sumber Kamera menyuruh proses line keluar
(`os._exit`), lalu `restart: unless-stopped` menyalakannya lagi — tapi yang
dinyalakan adalah container yang SAMA, dengan environment yang sama pula.
Setelan baru di `media.env` tidak pernah terbaca.

Terbukti di Lampung 2026-09-23: layar dipindah dari Foto ke Video, `media.env`
berubah, line benar-benar restart, dan gambarnya tetap foto.

Konsol tidak bisa membuat container baru — ia sengaja tidak diberi akses ke
Docker socket, dan memberikannya berarti konsol bisa mengendalikan seluruh
Docker di PC pabrik. Jadi line yang membaca berkasnya sendiri.

⚠️ `media.env` MENANG atas environment. Sebaliknya (environment menang) membuat
fitur ini mati total, karena compose selalu mengisi `CAMERA_TYPE` dari nilai
cadangannya (`hikrobot`) — tidak pernah kosong.
"""
from __future__ import annotations

import pytest

from palmgrade.core.config import Settings

ISI = """\
LINE_1_CAMERA_TYPE=opencv
LINE_1_MEDIA_FILE=konveyor.mp4
LINE_1_VIDEO_LOOP=true
LINE_2_CAMERA_TYPE=photo
LINE_2_MEDIA_FILE=sawit.jpg
LINE_2_VIDEO_LOOP=false
LINE_3_CAMERA_TYPE=hikrobot
LINE_3_MEDIA_FILE=
LINE_3_VIDEO_LOOP=false
"""

#: MACHINE_ID bawaan tiap line, dari `_CONSOLE_LINE_DEFAULTS`.
MID = {
    "line-1": "d1f9c7b2-8e5a-4c3b-9a1e-2f6d4c8e7b01",
    "line-2": "a7e2f4c9-3b6d-4e1a-8c5f-9d2b6a1e4f02",
    "line-3": "ad5f7bb9-c06d-4e87-8282-ce450ae331ec",
}


@pytest.fixture
def media_env(tmp_path):
    berkas = tmp_path / "media.env"
    berkas.write_text(ISI, encoding="utf-8")
    return berkas


def _settings(monkeypatch, media_env, line: str, **env) -> Settings:
    for k in ("CAMERA_TYPE", "MEDIA_FILE", "CAMERA_VIDEO_LOOP",
              "CAMERA_VIDEO_PATH", "CAMERA_PHOTO_PATH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MEDIA_ENV_PATH", str(media_env))
    monkeypatch.setenv("MACHINE_ID", MID[line])
    monkeypatch.setenv("MEDIA_DIR", "/media")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings()


def test_line_1_ambil_barisnya_sendiri(monkeypatch, media_env):
    s = _settings(monkeypatch, media_env, "line-1", CAMERA_TYPE="hikrobot")
    assert s.sumber_kamera() == "video"
    assert s.media_file == "konveyor.mp4"


def test_line_2_ambil_barisnya_sendiri(monkeypatch, media_env):
    # Bukti tiga line dibaca TERPISAH: satu nilai untuk ketiganya tidak
    # membuktikan apa-apa — mekanisme yang rusak pun menyamakan semuanya.
    s = _settings(monkeypatch, media_env, "line-2", CAMERA_TYPE="hikrobot")
    assert s.sumber_kamera() == "foto"
    assert s.media_file == "sawit.jpg"


def test_line_3_hikrobot_tanpa_berkas(monkeypatch, media_env):
    s = _settings(monkeypatch, media_env, "line-3", CAMERA_TYPE="opencv")
    assert s.sumber_kamera() == "hikrobot"
    assert s.media_file == ""


def test_media_env_menang_atas_environment(monkeypatch, media_env):
    """Inti perbaikan ini.

    Compose SELALU mengisi `CAMERA_TYPE` — nilai cadangannya `hikrobot`, tidak
    pernah kosong. Kalau environment yang menang, `media.env` tidak akan pernah
    terpakai dan fitur ini mati diam-diam.
    """
    s = _settings(monkeypatch, media_env, "line-1",
                  CAMERA_TYPE="hikrobot", MEDIA_FILE="jangan-dipakai.jpg")
    assert s.sumber_kamera() == "video"
    assert s.media_file == "konveyor.mp4"


def test_loop_ikut_dibaca(monkeypatch, media_env):
    s = _settings(monkeypatch, media_env, "line-1", CAMERA_VIDEO_LOOP="false")
    assert s.camera_video_loop is True


def test_tanpa_berkas_jatuh_ke_environment(monkeypatch, tmp_path):
    """Berkas tidak ada = keadaan normal, bukan kerusakan.

    Jalur native (`make line`) dan PC yang belum memakai layar Sumber Kamera
    tidak punya `media.env`. Keduanya harus tetap boot memakai environment.
    """
    s = _settings(monkeypatch, tmp_path / "tidak-ada.env", "line-1",
                  CAMERA_TYPE="photo", MEDIA_FILE="dari-env.jpg")
    assert s.sumber_kamera() == "foto"
    assert s.media_file == "dari-env.jpg"


def test_baris_line_lain_tidak_bocor(monkeypatch, tmp_path):
    """Hanya baris line INI yang dibaca.

    Kontrol negatif: berkas yang cuma punya baris line-2 tidak boleh membuat
    line-1 memakai setelan line-2 — gejalanya dua line menampilkan sumber yang
    sama dan tidak ada yang tahu kenapa.
    """
    berkas = tmp_path / "media.env"
    berkas.write_text("LINE_2_CAMERA_TYPE=photo\nLINE_2_MEDIA_FILE=sawit.jpg\n",
                      encoding="utf-8")
    s = _settings(monkeypatch, berkas, "line-1", CAMERA_TYPE="hikrobot")
    assert s.sumber_kamera() == "hikrobot"
    assert s.media_file == ""


def test_berkas_rusak_tidak_menghentikan_boot(monkeypatch, tmp_path):
    """Berkas ngawur = boot memakai environment, bukan line yang mati.

    Line yang gagal boot akan dinyalakan ulang terus oleh
    `restart: unless-stopped` — satu salah ketik bisa menghentikan pabrik.
    """
    berkas = tmp_path / "media.env"
    berkas.write_text("ini bukan env\n\x00\xff bukan utf-8", encoding="latin-1")
    s = _settings(monkeypatch, berkas, "line-1", CAMERA_TYPE="photo",
                  MEDIA_FILE="dari-env.jpg")
    assert s.sumber_kamera() == "foto"
    assert s.media_file == "dari-env.jpg"
