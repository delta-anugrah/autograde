"""OPS-2: satu truk fisik jadi satu baris, dijalankan sekali saat pasang PC pabrik.

PC pabrik yang sudah jalan menyimpan truk ber-id acak dari palmgrade-api
(`gen_random_uuid()`), sedangkan AutoGrade menurunkan id truk dari platnya
(`uuid5`, `domain/plate.py`). Kolom `plate_number` **tidak** punya indeks unik,
jadi tarikan master data pertama menambah baris kedua untuk truk yang sama:
operator melihat dua truk berplat sama di dropdown, dan tonase satu truk
terbelah dua tanpa ada apa pun di layar yang mengatakannya.

Id acak lama tidak bisa dihitung ulang dari apa pun, jadi satu-satunya jembatan
adalah **plat ternormalisasi** — dan normalisasinya harus persis yang dipakai
`truck_id_for`, kalau tidak truk yang mestinya digabung malah dilewati.

Mengikuti aturan OPS-2 di `autoerp/docs/autograde-integration.md`: cocokkan truk
lewat plat ternormalisasi, dan **cetak yang tidak bisa dicocokkan** untuk
diperiksa orang. Rumahnya pindah ke sini karena `palmgrade-api` sudah pensiun
(Opsi B); aturannya tidak berubah.

Dijalankan lewat `make rekonsiliasi-truk`, dan **aman dijalankan dua kali**: yang
menjalankannya sedang mengerjakan sepuluh hal lain dan sering ragu apakah tadi
sudah jalan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..domain.operator_error import OperatorError
from ..domain.plate import truck_id_for
from ..repositories.console_repository import ConsoleStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Kecuali:
    """Satu truk yang tidak bisa dibetulkan otomatis, untuk dibaca orang."""

    truck_id: str
    plate_number: str | None
    alasan: str


@dataclass
class Hasil:
    digabung: int = 0
    dipindah: int = 0
    dilewati: int = 0
    kecuali: list[Kecuali] = field(default_factory=list)
    # Plat yang disentuh, supaya laporannya bisa disebut satu per satu.
    plat: list[str] = field(default_factory=list)

    def laporan(self) -> str:
        """Dibaca di terminal PC pabrik. Angka dulu, lalu yang butuh orang."""
        baris = [
            f"digabung : {self.digabung}",
            f"dipindah : {self.dipindah}",
            f"dilewati : {self.dilewati}  (id-nya sudah benar)",
        ]
        if self.plat:
            baris.append("")
            baris.append("Truk yang disentuh:")
            baris += [f"  - {p}" for p in self.plat]
        if self.kecuali:
            baris.append("")
            baris.append(f"PERLU DIPERIKSA ORANG ({len(self.kecuali)}):")
            baris += [
                f"  - {k.truck_id}  plat={k.plate_number!r}  {k.alasan}"
                for k in self.kecuali
            ]
        return "\n".join(baris)


def rekonsiliasi_truk(store: ConsoleStore, *, tulis: bool = True) -> Hasil:
    """Betulkan id truk supaya semuanya turunan plat. `tulis=False` cuma melihat.

    Mode lihat ada karena ini menyentuh tonase: dijalankan dulu, dibaca, baru
    diputuskan. Kalau mode itu ikut menulis, tidak ada gunanya punya mode itu.
    """
    hasil = Hasil()
    # Difoto dulu: barisnya berubah saat digabung, dan iterasi di atas daftar yang
    # sedang berubah melewatkan baris tanpa memberi tahu. `trucks_semua`, bukan
    # `trucks`: yang terakhir menyembunyikan baris `inactive`, dan baris inactive
    # ber-id lama tetap akan kembar begitu tarikan ERP membawa platnya.
    semua = store.trucks_semua()

    for truk in semua:
        truck_id = truk["id"]
        plat = truk.get("plate_number")
        try:
            benar = truck_id_for(plat or "")
        except OperatorError:
            # Satu baris rusak tidak boleh membatalkan sisanya: yang lain tetap
            # perlu dibetulkan sebelum PC ini dipakai.
            hasil.kecuali.append(Kecuali(truck_id, plat, "plat kosong atau tidak terbaca"))
            continue

        if truck_id == benar:
            hasil.dilewati += 1
            continue

        ada_pasangan = store.truck(benar) is not None
        if tulis:
            store.pindahkan_truk(truck_id, benar)
        if ada_pasangan:
            hasil.digabung += 1
        else:
            hasil.dipindah += 1
        # Plat apa adanya, bukan bentuk ternormalisasi: yang membacanya mencocokkan
        # dengan kertas di tangannya, dan `BE4412OFL` tidak tertulis di mana pun.
        hasil.plat.append(plat)

    logger.info(
        "Rekonsiliasi truk%s: %d digabung, %d dipindah, %d dilewati, %d perlu diperiksa",
        "" if tulis else " (mode lihat)",
        hasil.digabung, hasil.dipindah, hasil.dilewati, len(hasil.kecuali),
    )
    return hasil
