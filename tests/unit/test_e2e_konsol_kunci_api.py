"""Penjaga statis: kunci yang dibaca E2E konsol harus yang benar-benar dikirim API.

`tests/e2e/test_console_autoerp.py` butuh AutoERP dan konsol hidup, jadi di CI dia
**skip** — sebelas-belasnya. Artinya tidak ada satu pun yang menahan kunci di dalamnya
supaya tetap cocok dengan API: ganti nama field di konsol, dan berkas itu tetap hijau
(karena tidak jalan) sampai ada yang menyalakannya berbulan-bulan kemudian.

Itu persis yang terjadi. Skema konsol diseragamkan jadi Inggris di #93 (`nama` →
`full_name`, `sumber_label` → `source_label`), berkas E2E-nya tidak ikut, dan
kegagalannya baru ketahuan saat dijalankan lawan situs sungguhan — dicatat sebagai G4.

Tes ini membaca **sumbernya**, bukan memanggil apa pun: `_with_source_label()` di
`console_service.py` dan handler `/api/console/me` di `routes/console.py` adalah
tempat kedua kunci itu lahir. Jalan di CI tanpa ERP, tanpa konsol, tanpa jaringan —
yang membuatnya jadi satu-satunya hal yang menjaga berkas E2E itu tetap jujur di
antara dua kali orang menjalankannya.

⚠️ Yang dijaga cuma kunci yang dibaca E2E dari **API konsol**. Field milik AutoERP
(`grading_acc`, `scale_ticket_no`, dan kawan-kawan) tidak ada di repo ini, jadi
kontraknya tetap `autoerp/docs/autograde-integration.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "palmgrade"
E2E = Path(__file__).resolve().parents[1] / "e2e" / "test_console_autoerp.py"

# (kunci, berkas yang menerbitkannya) — satu baris per kunci yang dibaca E2E dari
# API konsol. Kalau salah satu berubah nama, tes ini merah di CI hari itu juga,
# bukan berbulan-bulan kemudian saat ada yang kebetulan punya ERP hidup.
KUNCI_API = (
    ("source_label", SRC / "services" / "console_service.py"),
    ("full_name", SRC / "routes" / "console.py"),
    ("supplier_name", SRC / "repositories" / "console_repository.py"),
    ("plate_number", SRC / "repositories" / "console_repository.py"),
    ("net_kg", SRC / "repositories" / "console_repository.py"),
)

# Nama-nama pra-#93 yang pernah ada di berkas E2E ini dan membuatnya mati diam-diam.
KUNCI_PENSIUN = ("sumber_label", "nama", "peran", "log_kejadian")


def _e2e() -> str:
    return E2E.read_text(encoding="utf-8")


def _kunci_yang_dibaca_e2e() -> set[str]:
    """Setiap `["..."]` di berkas E2E. Kasar dengan sengaja: yang dicari cuma
    apakah sebuah nama muncul, bukan mengurai ekspresinya."""
    return set(re.findall(r'\["([a-z_]+)"\]', _e2e()))


@pytest.mark.parametrize("kunci,berkas", KUNCI_API)
def test_kunci_yang_dibaca_e2e_memang_diterbitkan_sumbernya(kunci: str, berkas: Path):
    """Kalau E2E membacanya, kode yang mengirimnya harus menyebut nama yang sama."""
    if kunci not in _kunci_yang_dibaca_e2e():
        pytest.skip(f"{kunci} tidak lagi dibaca E2E")

    assert berkas.exists(), f"{berkas} pindah; daftar di tes ini ikut diperbarui"
    sumber = berkas.read_text(encoding="utf-8")

    # Dua cara kunci lahir di repo ini, dan dua-duanya dihitung: string literal
    # (`row["source_label"] = ...`) dan alias SQL (`s.name AS supplier_name`).
    # Mencari yang pertama saja membuat tes ini merah untuk kunci yang sebenarnya
    # ada — ketemu saat menulisnya, dengan `supplier_name`.
    muncul = f'"{kunci}"' in sumber or re.search(rf"\bAS {kunci}\b", sumber)

    assert muncul, (
        f'E2E membaca ["{kunci}"] tapi {berkas.name} tidak menerbitkannya — '
        "kunci berganti nama dan berkas E2E tertinggal (ini G4)"
    )


@pytest.mark.parametrize("lama", KUNCI_PENSIUN)
def test_kunci_pra_inggris_tidak_kembali_ke_e2e(lama: str):
    """Skema konsol seluruhnya Inggris sejak #93.

    Dipisah dari tes di atas karena gagalnya beda: yang ini menangkap nama lama yang
    dihidupkan lagi, bukan nama baru yang belum ikut.
    """
    assert lama not in _kunci_yang_dibaca_e2e(), (
        f'["{lama}"] adalah kunci pra-#93; API konsol tidak mengirimnya lagi'
    )


def test_source_label_lahir_di_satu_tempat():
    """`_with_source_label()` satu-satunya yang memasang kunci ini (§3.5b).

    Kalau muncul tempat kedua, dua jalur bisa memberi label berbeda untuk truk yang
    sama — dan itu label yang menentukan potongan yang dibayar ke supplier.
    """
    service = (SRC / "services" / "console_service.py").read_text(encoding="utf-8")

    assert service.count('row["source_label"] =') == 1, (
        "lebih dari satu tempat memasang source_label"
    )


def test_berkas_e2e_masih_ada_di_tempatnya():
    """Seluruh tes di atas diam-diam lulus kalau berkasnya pindah atau hilang."""
    assert E2E.exists(), f"{E2E} tidak ada — penjaga ini jadi tidak menjaga apa pun"
    assert _kunci_yang_dibaca_e2e(), "tidak satu pun kunci terbaca; regex-nya perlu dicek"
