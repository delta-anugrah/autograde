"""`make hash-sandi` — hash untuk dua akun bawaan image (Fase 4, plan §6.5).

Dipakai sekali per PKS, waktu pasang PC, oleh orang yang sedang mengerjakan sepuluh hal
lain. Yang dijaga di sini bukan "fungsinya jalan", tapi hal-hal yang kalau salah baru
ketahuan berbulan-bulan kemudian:

- dua akun harus dapat sandi **berbeda** — kalau tertukar atau disamakan, jalur masuk
  support jadi sama dengan jalur operator, dan satu bocor membuka dua-duanya
- yang dicetak harus **hash**, bukan sandinya
- versi `$$` untuk docker-compose harus benar; salah satu `$` saja hash-nya terpotong
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from palmgrade.domain.operator_auth import verify_password
from palmgrade.services.akun_bawaan import EMAIL_BAWAAN, EMAIL_SUPPORT

SKRIP = Path(__file__).resolve().parents[2] / "scripts" / "hash-sandi.py"
SRC = Path(__file__).resolve().parents[2] / "src"

SANDI_OPERATOR = "operatorpabrik2026"
SANDI_SUPPORT = "supportkita2026"


def _jalankan(masukan: str) -> subprocess.CompletedProcess:
    """Skripnya dijalankan sungguhan, bukan diimpor: yang diuji termasuk urutan
    pertanyaannya, dan itu cuma ada kalau `main()` benar-benar jalan."""
    return subprocess.run(
        [sys.executable, str(SKRIP)],
        input=masukan,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
    )


def _hash_dari(keluaran: str, variabel: str) -> str:
    """Ambil nilai hash dari baris `docker build --build-arg VAR='...'`."""
    for baris in keluaran.splitlines():
        if f"{variabel}='" in baris:
            return baris.split(f"{variabel}='", 1)[1].split("'", 1)[0]
    raise AssertionError(f"{variabel} tidak ada di keluaran:\n{keluaran}")


def test_dua_akun_dapat_sandi_masing_masing():
    """Ini alasan utama skripnya menanyakan dua-duanya sekaligus: kalau operator harus
    menjalankannya dua kali dan mengingat sendiri mana untuk siapa, cepat atau lambat
    keduanya diisi sandi yang sama."""
    hasil = _jalankan(f"{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n{SANDI_SUPPORT}\n{SANDI_SUPPORT}\n")

    assert hasil.returncode == 0, hasil.stderr
    h_operator = _hash_dari(hasil.stdout, "CONSOLE_DEFAULT_HASH")
    h_support = _hash_dari(hasil.stdout, "CONSOLE_SUPPORT_HASH")

    assert verify_password(SANDI_OPERATOR, h_operator)
    assert verify_password(SANDI_SUPPORT, h_support)
    # Dan tidak tertukar:
    assert not verify_password(SANDI_SUPPORT, h_operator)
    assert not verify_password(SANDI_OPERATOR, h_support)


def test_sandi_yang_sama_untuk_dua_akun_ditolak():
    """Satu sandi untuk dua akun berarti jalur masuk developer sama dengan jalur
    operator — dan operator pabrik tahu sandinya."""
    hasil = _jalankan(f"{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n")

    assert hasil.returncode != 0
    assert "sama" in (hasil.stdout + hasil.stderr).lower()


def test_sandi_mentah_tidak_pernah_ikut_tercetak():
    """Yang dicetak disalin ke `.env` atau perintah build, dan sering ikut ter-paste ke
    chat. Sandi mentah di situ membatalkan seluruh gunanya menanam hash."""
    hasil = _jalankan(f"{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n{SANDI_SUPPORT}\n{SANDI_SUPPORT}\n")

    assert SANDI_OPERATOR not in hasil.stdout
    assert SANDI_SUPPORT not in hasil.stdout


def test_versi_untuk_compose_menggandakan_dollar():
    """docker-compose memakan `$`. Satu saja terlewat, hash-nya sampai terpotong dan
    akunnya ditolak — dengan pesan error, tapi tetap saja PC-nya tidak bisa dibuka."""
    hasil = _jalankan(f"{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n{SANDI_SUPPORT}\n{SANDI_SUPPORT}\n")

    h_operator = _hash_dari(hasil.stdout, "CONSOLE_DEFAULT_HASH")
    baris_env = [b for b in hasil.stdout.splitlines() if b.strip().startswith("CONSOLE_DEFAULT_HASH=")]

    assert baris_env, f"baris .env tidak ada:\n{hasil.stdout}"
    nilai = baris_env[0].split("=", 1)[1].strip()
    assert nilai == h_operator.replace("$", "$$")
    assert nilai.replace("$$", "$") == h_operator


def test_sandi_kedua_yang_beda_ditolak_sebelum_apa_pun_dicetak():
    """Diketik buta di terminal; satu salah ketik tidak boleh jadi hash yang tidak ada
    yang tahu sandinya."""
    hasil = _jalankan(f"{SANDI_OPERATOR}\nsalahketik2026\n")

    assert hasil.returncode != 0
    assert "CONSOLE_DEFAULT_HASH" not in hasil.stdout


def test_sandi_terlalu_pendek_ditolak():
    hasil = _jalankan("sawit12\nsawit12\n")

    assert hasil.returncode != 0
    assert "CONSOLE_DEFAULT_HASH" not in hasil.stdout


def test_kedua_email_disebut_supaya_tidak_salah_pasang():
    """Yang menjalankan ini sedang mengerjakan sepuluh hal lain; layarnya harus
    mengatakan hash mana untuk akun mana."""
    hasil = _jalankan(f"{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n{SANDI_SUPPORT}\n{SANDI_SUPPORT}\n")

    assert EMAIL_BAWAAN in hasil.stdout
    assert EMAIL_SUPPORT in hasil.stdout


def test_keluarannya_cuma_dua_akun_tanpa_basa_basi():
    """Yang dicetak ini disalin orang ke `.env`. Tiap baris yang bukan hash atau nama
    akun menambah peluang salah salin, jadi pembatas dan kalimat penutup tidak dicetak."""
    hasil = _jalankan(f"{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n{SANDI_SUPPORT}\n{SANDI_SUPPORT}\n")

    assert "=" * 20 not in hasil.stdout
    # Blok hasil = dari baris akun pertama sampai habis. Isinya persis enam baris: tiap
    # akun satu judul + build arg + baris .env, tidak ada pengantar atau penutup.
    baris = hasil.stdout.splitlines()
    mulai = next(i for i, b in enumerate(baris) if b.startswith("[operator pabrik]"))
    blok = [b for b in baris[mulai:] if b.strip()]
    assert len(blok) == 6, "blok hasil bukan 6 baris:\n" + "\n".join(blok)


def test_tidak_memakai_em_dash():
    """Em dash sering berubah jadi karakter rusak di terminal PC pabrik dan waktu
    disalin ke catatan. Dihindari di seluruh keluaran."""
    hasil = _jalankan(f"{SANDI_OPERATOR}\n{SANDI_OPERATOR}\n{SANDI_SUPPORT}\n{SANDI_SUPPORT}\n")

    assert "—" not in hasil.stdout + hasil.stderr
