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

# `docker compose config` di bawah menuntut `--env-file .env`, dan `.env` itu
# keadaan per-mesin yang di-`.gitignore` — runner CI tidak pernah punya. Menanyakan
# `docker` saja tidak cukup: runner GitHub PUNYA docker, jadi skip-nya tidak kena
# dan test gagal dengan "couldn't find env file" yang tidak ada hubungannya dengan
# apa yang diperiksa. Sudah terjadi: PR #128 membuat `staging` merah karena ini.
_ADA_DOCKER = shutil.which("docker") is not None
_ADA_ENV = (REPO_ROOT / ".env").exists()
butuh_docker = pytest.mark.skipif(
    not (_ADA_DOCKER and _ADA_ENV),
    reason="butuh docker + .env (keduanya tidak ada di runner CI)",
)


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


def test_console_native_menunjuk_folder_media_repo():
    """`make console` (native, tanpa Docker) harus menimpa MEDIA_DIR.

    Bawaan `Settings` adalah `/media` dan `/config/media.env` — path DI DALAM
    container, yang di compose datang dari mount `./media:/media`. Jalur native
    tidak punya mount itu, jadi tanpa penimpaan ini `MediaLibrary` menatap
    folder yang tidak ada dan memulangkan daftar KOSONG tanpa galat (folder
    hilang = kosong, itu memang perilakunya). Gejalanya: layar Sumber Kamera
    bilang "belum ada berkas" walau `media/` di repo berisi — terbaca seperti
    fitur rusak. Sudah terjadi sekali, 2026-09-21.
    """
    teks = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    resep = teks.split("\nconsole:\n", 1)
    assert len(resep) == 2, "target `console:` tidak ditemukan di Makefile"
    badan = resep[1].split("\n\n", 1)[0]
    assert "MEDIA_DIR=$(CURDIR)/media" in badan
    assert "MEDIA_ENV_PATH=$(CURDIR)/$(MEDIA_ENV)" in badan


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


def test_make_line_menyalakan_ulang_dan_membaca_media_env_tiap_putaran():
    """`make line` harus berputar dan membaca `media.env` ulang tiap putaran.

    Layar Sumber Kamera merestart line dengan menyuruh prosesnya KELUAR
    (`POST /internal/restart`). Di pabrik `restart: unless-stopped` milik Docker
    yang menyalakannya lagi; jalur native tidak punya siapa-siapa. Tanpa loop,
    "Simpan & Restart" mematikan line dan tidak pernah menghidupkannya — layar
    bilang tersimpan, kartunya jadi OFFLINE, nol galat yang menjelaskan.
    Terjadi 2026-09-21.

    Pembacaan `media.env` harus di DALAM loop: setelan baru itulah alasan
    prosesnya keluar, jadi nilai yang dihitung sekali saat start akan
    menyalakannya kembali dengan sumber yang lama.
    """
    teks = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    awal = teks.find("\nline:\n")
    assert awal != -1, "target `line:` tidak ditemukan"
    resep = teks[awal : teks.find("\n\n", awal + 1)]
    assert "while true" in resep, "make line tidak berputar — restart dari layar mematikannya"
    assert "$(MEDIA_ENV)" in resep, "media.env tidak dibaca di dalam loop"
    assert "LINE_$(N)_CAMERA_TYPE" in resep
    # Keluar tidak normal harus MENGHENTIKAN loop, bukan jadi gagal-nyala terus.
    assert "exit $$RC" in resep


def test_restart_tidak_menjanjikan_docker():
    """Pesan keluar tidak boleh menyebut Docker.

    Jalur native dinyalakan ulang loop `make line`, bukan Docker. Pesan yang
    menyebut Docker di terminal itu membuat orang mencari container yang tidak
    ada — sudah terjadi 2026-09-21.
    """
    sumber = (REPO_ROOT / "src" / "palmgrade" / "routes" / "internal.py").read_text(
        encoding="utf-8"
    )
    awal = sumber.find("def _jadwalkan_keluar")
    assert awal != -1
    assert "Docker akan menyalakan ulang" not in sumber[awal:]


# --------------------------------------------------- MEDIA_DIR di TIAP line


@butuh_docker
@pytest.mark.parametrize("service", LINES)
def test_tiap_line_dapat_media_dir(dirender, service):
    """`MEDIA_DIR` wajib sampai ke tiap line, bukan cuma ke konsol.

    Tanpa ini `core/config.media_dir` turun ke bawaannya `repo_root/media` —
    folder yang di dalam container tidak ada. Untuk `video` akibatnya
    `rencana_kamera()` menunjuk berkas yang tidak terbuka, `main.py` jatuh ke
    `CAMERA_DEVICE_INDEX`, dan line mencari webcam yang tidak terpasang:
    `RuntimeError: Tidak bisa buka camera source: 2`. Karena line memakai
    `restart: unless-stopped`, itu jadi crash-loop selamanya.

    Terbukti di Lampung 2026-09-23, dan tidak terlihat dari layar: setelannya
    benar, `media.env` benar, berkasnya ada di mount.
    """
    assert _env(dirender, service).get("MEDIA_DIR") == "/media"


@butuh_docker
@pytest.mark.parametrize("service", LINES)
def test_media_dir_menunjuk_mount_yang_benar(dirender, service):
    """`MEDIA_DIR` harus menunjuk folder yang BENAR-BENAR di-mount.

    Kontrol negatif untuk test di atas: `/media` yang benar tapi tidak
    di-mount akan memulangkan daftar kosong tanpa galat — `MediaLibrary`
    sengaja begitu — jadi nilainya saja tidak membuktikan apa-apa.
    """
    assert _env(dirender, service)["MEDIA_DIR"] in _target_mount(dirender, service)


@butuh_docker
@pytest.mark.parametrize("service", LINES)
def test_media_dir_selamat_dari_override_prod(dirender_prod, service):
    """Override `prod` MENGGANTI blok `environment:`, bukan menambahinya.

    Hari ini `prod` cuma menimpa `console`, jadi line aman. Test ini yang
    memberi tahu kalau suatu hari `prod` mulai menyebut `environment:` untuk
    line — gejalanya kalau tidak dijaga: line kembali crash-loop dan tidak ada
    satu pun galat yang menunjuk ke compose.
    """
    assert _env(dirender_prod, service).get("MEDIA_DIR") == "/media"


# ------------------------------------------- media.env sampai ke TIAP line


@butuh_docker
@pytest.mark.parametrize("service", LINES)
def test_tiap_line_memount_media_env(dirender, service):
    """Line membaca `media.env` sendiri, jadi berkasnya harus ada di dalamnya.

    Environment container BEKU sejak container dibuat. Tombol "Simpan &
    Restart" cuma menyuruh proses line keluar; `restart: unless-stopped`
    menyalakan container yang SAMA dengan environment yang sama. Tanpa mount
    ini setelan baru tidak pernah sampai — layar bilang Video, gambarnya tetap
    foto. Terbukti di Lampung 2026-09-23.
    """
    assert "/config/media.env" in _target_mount(dirender, service)


@butuh_docker
@pytest.mark.parametrize("service", LINES)
def test_line_tahu_di_mana_media_env(dirender, service):
    """Mount saja tidak cukup: line membacanya lewat `MEDIA_ENV_PATH`.

    Kontrol negatif untuk test di atas — berkas yang ter-mount tapi tidak
    pernah dicari sama saja dengan tidak ada, dan tidak ada galat yang muncul.
    """
    assert _env(dirender, service).get("MEDIA_ENV_PATH") == "/config/media.env"


@butuh_docker
@pytest.mark.parametrize("service", LINES)
def test_mount_media_env_selamat_dari_override_prod(dirender_prod, service):
    """`prod` memakai `volumes: !override`, yang MENGGANTI daftar volumes.

    Ini yang paling gampang hilang: menambah mount di compose dasar saja
    membuatnya lenyap di pabrik tanpa satu pun galat — gejalanya persis seperti
    fitur yang tidak pernah bekerja.
    """
    assert "/config/media.env" in _target_mount(dirender_prod, service)
