"""Dua peran akun konsol, dan penyaring untuk peran yang datang dari AutoERP.

Murni aturan, tanpa I/O — yang menyimpannya `console_repository`, yang menegakkannya
`routes/console.py`.

Sengaja hanya dua: dari lima layar developer tidak ada satu pun yang masuk akal
dibuka untuk yang satu tapi ditutup untuk yang lain. Peran ketiga akan jadi nama
kedua untuk hal yang sama, dan satu tempat lagi untuk salah setel.
"""

from __future__ import annotations

PERAN_OPERATOR = "operator"
PERAN_SUPPORT = "support"

_DIKENAL = frozenset({PERAN_OPERATOR, PERAN_SUPPORT})


def peran_sah(nilai: object) -> str:
    """Peran yang dikenal, atau `operator`.

    Apa pun yang aneh jatuh ke peran paling sempit, tidak pernah melempar: baris
    yang rusak harus tetap bisa login sebagai operator biasa, bukan mengunci
    layar pabrik.
    """
    if not isinstance(nilai, str):
        return PERAN_OPERATOR
    bersih = nilai.strip().lower()
    return bersih if bersih in _DIKENAL else PERAN_OPERATOR


def parse_daftar_izin(mentah: str) -> frozenset[str]:
    """`PERAN_ERP_DIIZINKAN` jadi himpunan peran yang boleh datang dari ERP."""
    if not mentah:
        return frozenset()
    return frozenset(
        bagian.strip().lower() for bagian in mentah.split(",") if bagian.strip()
    )


def saring_peran_erp(nilai: object, diizinkan: frozenset[str]) -> str:
    """Peran dari AutoERP, tapi hanya kalau PC ini mengizinkannya.

    Satu-satunya rem yang bisa ditarik dari sisi pabrik: kosongkan setelan, restart,
    dan tidak ada akun ERP yang bisa membuka layar developer — tanpa menunggu ERP
    dibereskan lebih dulu.
    """
    peran = peran_sah(nilai)
    return peran if peran in diizinkan else PERAN_OPERATOR
