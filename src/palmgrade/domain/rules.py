"""DIPENSIUNKAN 2026-09-16 — jangan dipakai, jangan dihidupkan lagi.

`derive_ripeness_status` menurunkan verdict dari substring `"rej"` di nama kelas.
Itu benar selama model masih 3 kelas (`ACC`/`Rej`/`TP`), dan **salah total** buat
model 4 kelas: `Unripe` dan `JK` tidak mengandung "rej", jadi keduanya akan
dibaca ACC — janjang mentah dan janjang kosong lolos ke pabrik tanpa satu pun
pesan error.

Fungsi ini sudah tidak dipanggil produksi sejak lama (aturan yang sebenarnya
hidup inline di `workers/frame_processing_worker.py`, dan sekarang di
`domain/grade_class.py`). Dibiarkan ada supaya `tests/unit/test_rules.py` yang
mengunci perilaku lamanya tetap jalan — bukan supaya dipakai lagi.

Yang benar: `grade_class_of()` lalu `verdict_for_class()` di
`domain/grade_class.py`. Keduanya mencocokkan NAMA kelas, bukan substring.
"""


def derive_ripeness_status(label: str, area: int = 0, minimum_size: int = 0) -> str:
    """JANGAN DIPAKAI untuk model 4 kelas. Lihat docstring modul."""
    if area > 0 and minimum_size > 0 and area < minimum_size:
        return "rej"
    return "rej" if "rej" in label.lower() else "acc"
