"""Compose benar-benar MENERUSKAN setelan sumber per line ke container.

⚠️ Test ini merender `docker compose config` dan membaca hasilnya. Itu
disengaja, dan versi sebelumnya yang cuma mencocokkan teks YAML adalah alasan
kenapa: ia menyatakan `env["CAMERA_TYPE"] == "${LINE_1_CAMERA_TYPE:-hikrobot}"`,
yang cuma membuktikan berkasnya berisi apa yang berkasnya berisi. Seluruh fitur
ini mati (`env_file:` tidak ikut interpolasi, jadi ketiga line selalu
`hikrobot`) sementara 1435 test hijau — termasuk test ini.

⚠️ Yang diperiksa `CAMERA_TYPE` / `MEDIA_FILE` / `CAMERA_VIDEO_LOOP` — variabel
yang sungguh dibaca `core/config.py`. **Jangan** memeriksa `LINE_1_*`: nama-nama
itu bocor ke environment container walau mekanismenya rusak, dan justru itu yang
membuat versi rusak terlihat sehat.

Tanpa `docker` test ini di-SKIP, bukan gagal: CI runner tidak punya Docker, dan
gerbang yang merah di mesin yang memang tidak bisa menjalankannya akan diabaikan
orang sampai tidak berarti apa-apa lagi.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_YML = REPO_ROOT / "docker-compose.yml"
COMPOSE_PROD = REPO_ROOT / "docker-compose.prod.yml"
MEDIA_ENV = REPO_ROOT / "media.env"

COMPOSE = yaml.safe_load(COMPOSE_YML.read_text(encoding="utf-8"))

LINES = ("ripe-line-1", "ripe-line-2", "ripe-line-3")

#: Setelan uji: tiap line sumber BERBEDA. Satu nilai untuk ketiganya tidak
#: membuktikan apa-apa — `env_file:` yang rusak pun membuat ketiganya sama.
SETELAN_UJI = """\
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

_ADA_DOCKER = shutil.which("docker") is not None
butuh_docker = pytest.mark.skipif(_ADA_DOCKER is False, reason="docker tidak ada")


def _render(berkas_prod: bool) -> dict:
    """`docker compose config` dengan `media.env` sementara, lalu dibereskan.

    `media.env` itu keadaan per-mesin yang di-`.gitignore`. Kalau developer yang
    menjalankan test punya berkasnya, isinya disimpan dan dikembalikan — test
    yang menghapus setelan orang adalah test yang dimatikan orang.
    """
    ada_sebelumnya = MEDIA_ENV.exists()
    asli = MEDIA_ENV.read_text(encoding="utf-8") if ada_sebelumnya else None
    MEDIA_ENV.write_text(SETELAN_UJI, encoding="utf-8")
    perintah = ["docker", "compose"]
    if berkas_prod:
        perintah += ["-f", str(COMPOSE_YML), "-f", str(COMPOSE_PROD)]
    perintah += [
        "--env-file", str(REPO_ROOT / ".env"),
        "--env-file", str(MEDIA_ENV),
        "config", "--format", "json",
    ]
    try:
        hasil = subprocess.run(
            perintah, cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
        )
    finally:
        if asli is None:
            MEDIA_ENV.unlink(missing_ok=True)
        else:
            MEDIA_ENV.write_text(asli, encoding="utf-8")
    if hasil.returncode != 0:
        pytest.fail(f"docker compose config gagal:\n{hasil.stderr}")
    return json.loads(hasil.stdout)


@pytest.fixture(scope="module")
def dirender():
    return _render(berkas_prod=False)


@pytest.fixture(scope="module")
def dirender_prod():
    return _render(berkas_prod=True)


def _env(rendered: dict, service: str) -> dict[str, str]:
    return rendered["services"][service]["environment"]


def _target_mount(rendered: dict, service: str) -> list[str]:
    return [v["target"] for v in rendered["services"][service].get("volumes", [])]


# --------------------------------------------------------------- C1: rendered


@butuh_docker
def test_tiap_line_merender_sumbernya_sendiri(dirender):
    # Inti C1: tiga line, tiga nilai BERBEDA, dibaca dari hasil render.
    assert _env(dirender, "ripe-line-1")["CAMERA_TYPE"] == "opencv"
    assert _env(dirender, "ripe-line-2")["CAMERA_TYPE"] == "photo"
    assert _env(dirender, "ripe-line-3")["CAMERA_TYPE"] == "hikrobot"


@butuh_docker
def test_berkas_media_sampai_ke_line_yang_benar(dirender):
    assert _env(dirender, "ripe-line-1")["MEDIA_FILE"] == "konveyor.mp4"
    assert _env(dirender, "ripe-line-2")["MEDIA_FILE"] == "sawit.jpg"
    assert _env(dirender, "ripe-line-3")["MEDIA_FILE"] == ""


@butuh_docker
def test_ulang_video_per_line(dirender):
    assert _env(dirender, "ripe-line-1")["CAMERA_VIDEO_LOOP"] == "true"
    assert _env(dirender, "ripe-line-2")["CAMERA_VIDEO_LOOP"] == "false"


@butuh_docker
def test_konsol_tahu_letak_media(dirender):
    env = _env(dirender, "console")
    assert env["MEDIA_DIR"] == "/media"
    assert env["MEDIA_ENV_PATH"] == "/config/media.env"


# ------------------------------------------------- C3: override produksi juga


@butuh_docker
def test_prod_tetap_merender_sumber_per_line(dirender_prod):
    # `docker-compose.prod.yml` memakai `volumes: !override` dan menulis ulang
    # seluruh blok `environment:` konsol. Keduanya gampang ketinggalan.
    assert _env(dirender_prod, "ripe-line-1")["CAMERA_TYPE"] == "opencv"
    assert _env(dirender_prod, "ripe-line-2")["CAMERA_TYPE"] == "photo"
    assert _env(dirender_prod, "ripe-line-3")["CAMERA_TYPE"] == "hikrobot"


@butuh_docker
def test_prod_konsol_tetap_punya_setelan_media(dirender_prod):
    # Compose v2.40.3 di PC Lampung MEMBUANG blok `environment:` dasar begitu
    # override menyebut kunci itu (autograde#120). Ketiga variabel ini harus
    # ditulis ulang di override, bukan diwarisi.
    env = _env(dirender_prod, "console")
    assert env["MEDIA_DIR"] == "/media"
    assert env["MEDIA_ENV_PATH"] == "/config/media.env"
    assert "MEDIA_FILE" in env


@butuh_docker
def test_prod_semua_service_tetap_memount_media(dirender_prod):
    for service in (*LINES, "console"):
        assert "/media" in _target_mount(dirender_prod, service), service
    assert "/config/media.env" in _target_mount(dirender_prod, "console")


# ------------------------------------------------- invarian statis yang sisa


def test_env_file_tidak_dipakai_untuk_media_env():
    # `env_file:` menyuntik environment container SESUDAH interpolasi, jadi ia
    # tidak pernah bisa mengisi `${LINE_1_CAMERA_TYPE}`. Memakainya di sini
    # adalah persis bug C1 — dan bug itu senyap sempurna.
    for service in (*LINES, "console"):
        env_file = COMPOSE["services"][service].get("env_file")
        assert not env_file, (
            f"{service} memakai env_file; media.env harus lewat --env-file"
        )


def test_makefile_membawa_kedua_env_file():
    teks = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "--env-file $(ENV_FILE) --env-file $(MEDIA_ENV)" in teks
    # Tidak boleh ada BARIS RESEP yang memanggil `docker compose` langsung:
    # semuanya harus lewat `$(COMPOSE)`/`$(COMPOSE_PROD)`, kalau tidak target
    # itu diam-diam kehilangan `media.env`. Cuma baris resep (diawali TAB) yang
    # diperiksa — definisi variabelnya sendiri memang menyebut `docker compose`.
    nakal = [
        baris
        for baris in teks.splitlines()
        if baris.startswith("\t") and "docker compose" in baris
        and "$(COMPOSE)" not in baris and "$(COMPOSE_PROD)" not in baris
        and "--env-file $(MEDIA_ENV)" not in baris
    ]
    assert not nakal, f"pemanggil tanpa media.env: {nakal}"


def test_makefile_membuat_media_env_kalau_hilang():
    # C2: `--env-file` yang berkasnya tidak ada = exit 1 untuk SEMUA target.
    teks = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "test -f $(MEDIA_ENV) || cp media.env.example $(MEDIA_ENV)" in teks


def test_media_env_tidak_ikut_git():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "media.env" in gitignore.split()


def test_contohnya_ikut_git_dan_bawaannya_hikrobot():
    # Berkas yang disalin penjaga Makefile. Kalau bawaannya bukan hikrobot,
    # clone bersih di PC pabrik akan mematikan kamera sungguhan.
    contoh = (REPO_ROOT / "media.env.example").read_text(encoding="utf-8")
    for i in (1, 2, 3):
        assert f"LINE_{i}_CAMERA_TYPE=hikrobot" in contoh


def test_bind_mount_video_lama_dibuang():
    # Bind-mount per berkas memilih berkasnya saat container DIBUAT; itulah yang
    # membuat memilih berkas dari layar mustahil sebelum ini.
    for service in LINES:
        vols = COMPOSE["services"][service].get("volumes", [])
        assert not any("/videos/video-in" in v for v in vols)


def test_konsol_tidak_memount_dotenv():
    # `.env` memuat lisensi, R2, dan webhook secret.
    vols = COMPOSE["services"]["console"].get("volumes", [])
    assert not any(v.startswith("./.env") for v in vols)
