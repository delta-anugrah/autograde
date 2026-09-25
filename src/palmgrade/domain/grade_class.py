"""The four classes `best.pt` detects, and the binary verdict they collapse to.

The model got more specific; two things downstream did not, on purpose:

- **the PLC has two coils**, OK and NG (`plc/worker.py:_coil_for`). A bunch is
  discarded or it is not. A third category would need a third piston, wiring and
  an ODOT change — hardware, not software.
- **AutoERP books three AI criteria**, `Mentah` / `Tangkai Panjang` / `Matang`
  (`erpnext/palm_mill/api.py:AI_CRITERIA`). That contract is frozen.

So this module keeps the two vocabularies apart rather than widening either:

| model class | verdict | piston | booked as |
|---|---|---|---|
| `Ripe`   | `ACC` | no  | Matang (derived by AutoERP) |
| `Unripe` | `REJ` | yes | Mentah |
| `JK`     | `REJ` | yes | Mentah — see below |
| `TP`     | none  | -   | Tangkai Panjang, via `tp_confidence` |

`ripeness_status` stays the verdict that fires pistons and is paid on;
`grade_class` is the detail the console shows. JK rides with REJ (decided
2026-09-16): an empty bunch is discarded like an unripe one. Its count is kept
on the edge and deliberately NOT sent to AutoERP — there is no `JK` criterion
there, and the two candidates both misreport: `Sampah` is *weighed*, not seen by
a camera (Samuel, 2026-09-16), and folding JK into `Mentah` would overstate the
unripe share the supplier is docked for. Sending it needs a contract change
agreed with Samuel first.

TP is not a bunch. It is a property of one — a long stalk on an otherwise
accepted bunch — so it has no verdict and never reaches the PLC.

Kept free of numpy/torch/cv2 so the light CI can test it (see `vision_event`).
"""
from __future__ import annotations

RIPE = "Ripe"
UNRIPE = "Unripe"
JK = "JK"
TP = "TP"

#: Every class the model may emit, in the order the console shows them.
GRADE_CLASSES = (RIPE, UNRIPE, JK, TP)

#: The classes that are a bunch and therefore get a verdict. TP is not one.
FRUIT_CLASSES = (RIPE, UNRIPE, JK)

# Matching is case-insensitive because the label text is training-set metadata,
# not an interface. The old model shipped `{0: 'ACC', 1: 'Rej', 2: 'TP'}` — three
# casings in three classes. Pinning exact case is how a retrain silently stops
# grading: every bunch falls through the match and no bunch is ever counted.
_BY_LOWER = {name.lower(): name for name in GRADE_CLASSES}

# The verdict each fruit class collapses to. TP is absent on purpose: `.get`
# returning None is what tells the caller "this is not a bunch".
_VERDICT = {RIPE: "ACC", UNRIPE: "REJ", JK: "REJ"}


def grade_class_of(label: str | None) -> str:
    """One model label, normalised to a member of `GRADE_CLASSES`.

    Raises `ValueError` for anything else, deliberately: an unknown class would
    be counted in `total` and in none of the four, and the recap the mill is paid
    on would not add up with nothing saying so.
    """
    normalised = _BY_LOWER.get(str(label or "").strip().lower())
    if normalised is None:
        raise ValueError(
            f"kelas model tidak dikenal: {label!r} - harus {' / '.join(GRADE_CLASSES)}"
        )
    return normalised


def verdict_for_class(grade_class: str) -> str | None:
    """`ACC`/`REJ` for a bunch, `None` for TP (which is not a bunch).

    `None` is the signal to leave the PLC alone: pulsing a coil for a long stalk
    would make the PLC count it as a fruit.
    """
    return _VERDICT.get(grade_class)


def is_fruit_class(grade_class: str) -> bool:
    """True when this class is a bunch that gets graded, i.e. not TP."""
    return grade_class in FRUIT_CLASSES


def grade_class_or_none(label: str | None) -> str | None:
    """Seperti `grade_class_of`, tapi memulangkan `None` alih-alih melempar.

    Dipakai di jalur yang tidak boleh menjatuhkan event gara-gara label: kolom
    ini cuma label buat layar, sedangkan `ripeness_status` yang dijumlah jadi
    angka bayaran tetap divalidasi keras. Kosong (`None`/`""`) juga `None` —
    capture manual tidak pernah lewat model, jadi kelasnya memang tidak ada.
    """
    if label is None or not str(label).strip():
        return None
    try:
        return grade_class_of(label)
    except ValueError:
        return None


def periksa_kelas(names) -> tuple[list[str], list[str]]:
    """(tidak dikenal, hilang) dari nama kelas sebuah model. Dua-duanya kosong = cocok.

    Satu aturan untuk dua pemakai: line memeriksa model yang BARU dimuatnya
    (`model_registry`), konsol memeriksa berkas SEBELUM boleh dipilih di layar
    Model Deteksi. Tanpa aturan bersama, dua tempat itu bisa berbeda pendapat
    soal model yang sama — dan yang kalah selalu yang di pabrik.

    Pencocokan ikut `grade_class_or_none`, jadi tidak peduli huruf besar-kecil.
    """
    names = [str(n) for n in names]
    dikenal = {grade_class_or_none(n) for n in names}
    asing = sorted(n for n in names if grade_class_or_none(n) is None)
    hilang = sorted(c for c in GRADE_CLASSES if c not in dikenal)
    return asing, hilang
