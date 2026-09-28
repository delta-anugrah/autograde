"""Berkas `.env` yang bisa terbaca `load_dotenv()` dari kode aplikasi.

`load_dotenv()` tanpa argumen memanggil `find_dotenv()`, yang naik dari folder
berkas pemanggilnya (`src/palmgrade/`) sampai akar sistem berkas dan memakai
`.env` PERTAMA yang ditemukan (atau naik dari cwd kalau debugger aktif). Di
checkout biasa itu `<repo>/.env`; di worktree itu `.env` checkout utama.
Conftest membersihkan kunci SEMUA berkas di jalur itu: membuang kunci yang tidak
ada di environ asli tidak pernah merugikan test mana pun.
"""
from __future__ import annotations

from pathlib import Path


def berkas_env_leluhur(mulai: Path) -> list[Path]:
    """Setiap `.env` dari `mulai` naik sampai akar, yang terdekat dulu."""
    return [folder / ".env" for folder in (mulai, *mulai.parents) if (folder / ".env").is_file()]


def kunci_env(berkas: list[Path]) -> list[str]:
    """Nama variabel di berkas-berkas itu, urut kemunculan, tanpa kembar."""
    kunci: list[str] = []
    for satu in berkas:
        for baris in satu.read_text(encoding="utf-8").splitlines():
            baris = baris.strip()
            if not baris or baris.startswith("#") or "=" not in baris:
                continue
            nama = baris.split("=", 1)[0].strip().removeprefix("export ").strip()
            if nama not in kunci:
                kunci.append(nama)
    return kunci
