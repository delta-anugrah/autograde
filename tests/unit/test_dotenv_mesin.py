"""Conftest harus membersihkan `.env` yang benar-benar dibaca `load_dotenv()`.

`find_dotenv()` naik dari folder kode sampai akar. Di worktree
(`<repo>/.claude/worktrees/<nama>/`) worktree-nya tidak punya `.env`, jadi yang
terbaca `.env` checkout utama di atasnya, dan dua test lulus-sendiri-gagal-bersama.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv
from dotenv_mesin import berkas_env_leluhur, kunci_env


def test_env_checkout_utama_di_atas_worktree_ikut_ditemukan(tmp_path):
    (tmp_path / ".env").write_text("PLC_ENABLED=true\n")
    kode = tmp_path / ".claude" / "worktrees" / "x" / "src" / "palmgrade"
    kode.mkdir(parents=True)

    assert berkas_env_leluhur(kode)[0] == tmp_path / ".env"


def test_berkas_pertama_sama_dengan_yang_dipakai_python_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("A=1\n")
    kode = tmp_path / "wt" / "src"
    kode.mkdir(parents=True)
    monkeypatch.chdir(kode)

    assert Path(find_dotenv(usecwd=True)) == berkas_env_leluhur(kode)[0]


def test_env_terdekat_didahulukan(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    dalam = tmp_path / "repo"
    dalam.mkdir()
    (dalam / ".env").write_text("B=2\n")

    assert berkas_env_leluhur(dalam)[:2] == [dalam / ".env", tmp_path / ".env"]


def test_kunci_env_membaca_export_dan_melewati_komentar(tmp_path):
    berkas = tmp_path / ".env"
    berkas.write_text("# komentar\nexport A=1\nB = 2\n\nC\nA=3\n")

    assert kunci_env([berkas]) == ["A", "B"]
