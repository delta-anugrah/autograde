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


def _db_dari_argumen() -> Path:
    """`--db <path>` menang atas setelan.

    Ada supaya rekonsiliasi bisa dicoba di SALINAN dulu. Tanpa ini satu-satunya cara
    mencobanya adalah menjalankannya di database pabrik yang sungguhan, dan itu
    persis yang tidak boleh dilakukan untuk memeriksa apakah hasilnya benar.
    """
    if "--db" in sys.argv:
        i = sys.argv.index("--db")
        if i + 1 >= len(sys.argv):
            raise SystemExit("--db butuh path")
        return Path(sys.argv[i + 1])
    return Path(Settings().console_db_path)


def main() -> int:
    tulis = "--tulis" in sys.argv
    db = _db_dari_argumen()
    if not db.exists():
        print(f"Database konsol tidak ada: {db}", file=sys.stderr)
        print("PC baru tidak perlu rekonsiliasi.", file=sys.stderr)
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
