#!/usr/bin/env python3
"""OPS-2: satukan truk kembar di PC pabrik yang sudah jalan.

    make rekonsiliasi-truk          # lihat dulu, tidak menulis apa pun
    make rekonsiliasi-truk TULIS=1  # kerjakan

    # Mencoba di salinan dulu (disarankan sebelum menyentuh yang asli):
    cp state/console.db /tmp/coba.db
    PYTHONPATH=src .venv/bin/python scripts/rekonsiliasi-truk.py --db /tmp/coba.db --tulis

Dijalankan **sekali** saat memasang AutoGrade di PC yang sudah punya data truk dari
palmgrade-api. Truk lama ber-id acak, AutoGrade menurunkan id dari plat, dan kolom
plat tidak punya indeks unik: tanpa ini, tarikan master data pertama membuat baris
kedua untuk truk yang sama dan tonase satu truk terbelah dua, tanpa ada apa pun di
layar yang mengatakannya.

PC pabrik baru (database kosong) tidak perlu menjalankan ini.

⚠️ Backup dulu `state/console.db` sebelum menjalankan dengan `TULIS=1`. Perintahnya
disebutkan lagi di layar sebelum menulis.
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ bukan package, dan image tidak menyetel PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from palmgrade.core.config import Settings  # noqa: E402
from palmgrade.repositories.console_repository import ConsoleStore  # noqa: E402
from palmgrade.services.rekonsiliasi import rekonsiliasi_truk  # noqa: E402


def _kandidat_db() -> list[Path]:
    """Tempat database konsol bisa berada, urut dari yang paling mungkin.

    Ada DUA bentuk, dan itu ketemu di PC Lampung 2026-09-15 waktu skrip ini menjawab
    "Database konsol tidak ada" padahal ada 53 MB di sana:

    - **native** (`make console` di Mac, atau dari DALAM container): `state/console.db`
    - **host, konsol di Docker**: `state/console/console.db` — compose me-mount
      `./state/console:/app/state`, jadi dari sisi host ada satu tingkat folder lagi

    `Settings.state_dir` diturunkan dari lokasi berkas kode, jadi dia selalu menunjuk
    bentuk pertama. Yang menjalankan ini sedang memasang PC pabrik dan tidak semestinya
    menebak mana yang berlaku, jadi keduanya dicari.
    """
    state = Path(Settings().state_dir)
    return [state / "console.db", state / "console" / "console.db"]


def _db_dari_argumen() -> Path | None:
    """`--db <path>` menang atas pencarian otomatis, None kalau tidak ada yang ketemu.

    Argumen itu ada supaya rekonsiliasi bisa dicoba di SALINAN dulu. Tanpa itu
    satu-satunya cara mencobanya adalah menjalankannya di database pabrik yang
    sungguhan — persis yang tidak boleh dilakukan untuk memeriksa hasilnya.
    """
    if "--db" in sys.argv:
        i = sys.argv.index("--db")
        if i + 1 >= len(sys.argv):
            raise SystemExit("--db butuh path")
        return Path(sys.argv[i + 1])
    return next((p for p in _kandidat_db() if p.exists()), None)


def main() -> int:
    tulis = "--tulis" in sys.argv
    db = _db_dari_argumen()
    if db is None or not db.exists():
        # Kedua tempat disebut: kalau cuma satu, yang membacanya menyimpulkan salah
        # checkout padahal database-nya ada — cuma di bentuk yang satunya.
        print("Database konsol tidak ada. Yang dicari:", file=sys.stderr)
        for kandidat in _kandidat_db():
            print(f"  - {kandidat}", file=sys.stderr)
        print(file=sys.stderr)
        print("PC baru memang belum punya, jadi tidak perlu rekonsiliasi.", file=sys.stderr)
        print("Kalau konsolnya jalan di tempat lain, tunjuk langsung:", file=sys.stderr)
        print("  scripts/rekonsiliasi-truk.py --db <path>", file=sys.stderr)
        return 1

    print(f"Database: {db}")
    print("Mode    :", "TULIS (mengubah data)" if tulis else "lihat saja")
    print()

    store = ConsoleStore(db)
    hasil = rekonsiliasi_truk(store, tulis=tulis)
    print(hasil.laporan())
    print()

    if not tulis:
        if hasil.digabung or hasil.dipindah:
            print("Belum ada yang diubah. Kalau laporan di atas sudah benar:")
            print(f"  cp {db} {db}.backup")
            print("  make rekonsiliasi-truk TULIS=1")
        else:
            print("Tidak ada yang perlu dibetulkan.")
        return 0

    print("Selesai.")
    if hasil.kecuali:
        # Bukan kegagalan: sisanya sudah dibetulkan. Tapi yang ini harus dilihat orang,
        # jadi keluar dengan kode tidak-nol supaya tidak lewat begitu saja di skrip.
        print()
        print("Ada truk yang tidak bisa dibetulkan otomatis (lihat daftar di atas).")
        print("Betulkan platnya di AutoERP, lalu jalankan lagi.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
