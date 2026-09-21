"""Tiap line menulis ke foldernya sendiri, juga saat jalan tanpa Docker.

Konsol menyajikan gambar dari `artifacts/{line_code}` (`console_main`:
`/captures/{line_code}`), dan di Docker itu otomatis benar karena tiap line punya
volume sendiri (`./artifacts/line-N:/app/artifacts`).

Jalur native (`make line`) tidak punya volume. Tanpa `ARTIFACTS_DIR`, tiga line
menulis ke satu `artifacts/` yang sama sementara konsol tetap mencari di
`artifacts/line-2/...` — gambarnya tersimpan, ukurannya benar, dan tiap tautan di
layar dijawab **404**. Gagalnya sunyi: tidak ada error di sisi line sama sekali.
"""
from __future__ import annotations

import pathlib

from palmgrade.core.config import Settings

AKAR = pathlib.Path(__file__).resolve().parents[2]


def test_env_menimpa_folder_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "line-9"))
    assert Settings().artifacts_dir == tmp_path / "line-9"


def test_tanpa_env_kembali_ke_bawaan(monkeypatch):
    """Docker tidak menyetelnya — di sana volume yang memisahkan."""
    monkeypatch.delenv("ARTIFACTS_DIR", raising=False)
    s = Settings()
    assert s.artifacts_dir == s.repo_root / "artifacts"


def test_kosong_dianggap_tidak_diset(monkeypatch):
    """`.env` yang menulis `ARTIFACTS_DIR=` tanpa nilai tidak boleh berarti
    "tulis ke folder bernama string kosong"."""
    monkeypatch.setenv("ARTIFACTS_DIR", "   ")
    s = Settings()
    assert s.artifacts_dir == s.repo_root / "artifacts"


def test_make_line_memberi_folder_berbeda_per_line():
    """Yang sebenarnya menangkap bug ini: N harus ikut ke dalam path."""
    makefile = (AKAR / "Makefile").read_text(encoding="utf-8")
    baris = [b for b in makefile.splitlines() if "ARTIFACTS_DIR=" in b]
    assert baris, "make line tidak menyetel ARTIFACTS_DIR"
    assert any("line-$(N)" in b for b in baris), (
        "ARTIFACTS_DIR harus mengandung $(N) — tanpa itu tiga line menulis ke "
        "folder yang sama dan konsol menjawab 404 untuk semua gambar"
    )


def test_konsol_menyajikan_dari_folder_per_line():
    """Sisi seberangnya, dikunci supaya kedua ujungnya tidak bisa berpisah."""
    konsol = (AKAR / "src" / "palmgrade" / "console_main.py").read_text(encoding="utf-8")
    assert "artifacts_dir / line.line_code" in konsol
    assert 'f"/captures/{line.line_code}"' in konsol


def test_mount_video_compose_tidak_dipatok_ke_mesin_siapa_pun():
    """Dulu `/home/nexio/Desktop/Projects/sawit:/videos:ro` — path milik satu
    laptop. Di PC lain folder itu tidak ada, jadi videonya tidak terlihat dari
    dalam container dan line mati saat start dengan "Tidak bisa buka camera
    source"."""
    compose = (AKAR / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/home/nexio" not in compose, "path mesin orang lain kembali masuk"


def test_satu_env_saja_untuk_video():
    """Bind-mount per berkas (`CAMERA_VIDEO_PATH` → `/videos/video-in`) DIBUANG
    di Task 11: ia memilih berkasnya saat container DIBUAT, yang membuat memilih
    dari layar Support mustahil. Diganti mount folder `media/` utuh — nama
    berkasnya sekarang datang dari `media.env` (`MEDIA_FILE`, per line),
    dibaca ulang tiap request, bukan dipatok saat container dibuat."""
    compose = (AKAR / "docker-compose.yml").read_text(encoding="utf-8")
    assert "VIDEOS_DIR" not in compose, "variabel kedua kembali masuk"
    assert "/videos/video-in" not in compose, "bind-mount per berkas lama kembali masuk"
    assert "CAMERA_VIDEO_PATH=${CAMERA_VIDEO_PATH" not in compose, "path per mesin lama kembali masuk"
    # 3 line + konsol = 4.
    assert compose.count("./media:/media:ro") == 4, "keempat service wajib mount folder media"


def test_env_example_tidak_lagi_menyuruh_menulis_path_container():
    contoh = (AKAR / ".env.example").read_text(encoding="utf-8")
    assert "VIDEOS_DIR" not in contoh
    assert "CAMERA_VIDEO_PATH=" not in contoh, "operator tidak lagi mengisi path di sini"
    # Sejak Task 11 penunjuknya ke media.env.example, bukan lagi path per mesin.
    assert "media.env.example" in contoh


def test_setiap_line_punya_volume_artifacts_sendiri_di_docker():
    """Jalur Docker tetap memisahkan lewat volume, bukan env."""
    compose = (AKAR / "docker-compose.yml").read_text(encoding="utf-8")
    for n in (1, 2, 3):
        assert f"./artifacts/line-{n}:/app/artifacts" in compose



