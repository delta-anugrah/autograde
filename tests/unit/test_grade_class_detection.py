"""Jalur deteksi: dari label YOLO ke verdict, tanpa menyeret torch ke CI.

Yang diuji di sini keputusan-keputusan yang diambil `FrameProcessingWorker` untuk
tiap kotak — dinormalkan lewat `_grade_class_or_none`, lalu dipakai untuk tiga
hal: apakah `area` dihitung (penjaga `MINIMUM_SIZE`), apakah kotaknya digrading,
dan coil mana yang ditembak.

`results.names` di-tiru sebagai dict biasa karena memang itu bentuknya di
ultralytics. Tidak ada torch di sini, sesuai CLAUDE.md § Tests.
"""
from __future__ import annotations

import pytest

from palmgrade.domain.grade_class import (
    JK,
    RIPE,
    TP,
    UNRIPE,
    is_fruit_class,
    verdict_for_class,
)
from palmgrade.workers.frame_processing_worker import _grade_class_or_none

# Urutan SEBENARNYA di `best.pt` (dibaca dari file, 2026-09-16). Ditulis apa
# adanya di sini supaya kalau model berikutnya menukar urutannya lagi, yang
# berubah cuma konstanta ini — bukan diam-diam mematikan penjaga ukuran.
URUTAN_ASLI = {0: "JK", 1: "Ripe", 2: "TP", 3: "Unripe"}

# Tiga cara model yang sah bisa menamai kelasnya. Ketiganya harus berujung sama.
URUTAN_NORMAL = {0: "Ripe", 1: "Unripe", 2: "JK", 3: "TP"}
URUTAN_DITUKAR = {0: "TP", 1: "JK", 2: "Ripe", 3: "Unripe"}
HURUF_BEDA = {0: "ripe", 1: "UNRIPE", 2: "jk", 3: "tp"}


def _keputusan(names: dict[int, str]) -> dict[str, tuple]:
    """Apa yang worker putuskan untuk tiap kotak: (kelas, verdict, area dihitung)."""
    hasil = {}
    for label in names.values():
        kelas = _grade_class_or_none(label)
        buah = kelas is not None and is_fruit_class(kelas)
        hasil[kelas or label] = (
            kelas,
            verdict_for_class(kelas) if kelas else None,
            buah,
        )
    return hasil


@pytest.mark.parametrize(
    "names",
    [URUTAN_ASLI, URUTAN_NORMAL, URUTAN_DITUKAR, HURUF_BEDA],
    ids=["best.pt-asli", "normal", "ditukar", "huruf"],
)
def test_keputusan_tidak_bergantung_urutan_atau_huruf(names):
    """Nama kelas itu metadata hasil latih, bukan antarmuka. Model yang dilatih
    ulang boleh menukar urutan dan mengubah ejaan besar-kecilnya."""
    d = _keputusan(names)
    assert d[RIPE] == (RIPE, "ACC", True)
    assert d[UNRIPE] == (UNRIPE, "REJ", True)
    assert d[JK] == (JK, "REJ", True)
    assert d[TP] == (TP, None, False)


def test_urutan_asli_best_pt_membuat_aturan_lama_melewatkan_unripe():
    """Bukan hipotesis: ini urutan kelas `best.pt` yang sungguhan.

    `cls_id in (0, 1)` pada urutan {0:JK, 1:Ripe, 2:TP, 3:Unripe} memberi
    `area = 0` untuk **Unripe** (id 3), jadi `area < MINIMUM_SIZE` berhenti
    menyaring buah mentah yang terlalu kecil: tiap Unripe mungil lolos sebagai
    REJ yang sah, tanpa error dan tanpa log. JK dan Ripe kebetulan selamat
    karena id-nya 0 dan 1 — kebetulan, bukan karena aturannya benar.
    """
    lama = {lab: (cid in (0, 1)) for cid, lab in URUTAN_ASLI.items()}
    assert lama["Unripe"] is False, "aturan lama melewatkan Unripe"
    assert lama["JK"] is True and lama["Ripe"] is True, "dua ini kebetulan selamat"

    baru = _keputusan(URUTAN_ASLI)
    assert baru[UNRIPE][2] is True, "sekarang Unripe ikut disaring MINIMUM_SIZE"
    assert baru[TP][2] is False, "TP tetap bukan buah"


def test_area_dihitung_untuk_buah_walau_urutan_kelas_ditukar():
    """Ini regresi yang sebenarnya: dulu barisnya `cls_id in (0, 1)`.

    Pada `URUTAN_DITUKAR`, id 0 dan 1 adalah TP dan JK — jadi Ripe dan Unripe
    dapat `area = 0`, dan `area < MINIMUM_SIZE` berhenti menyaring buah kecil
    tanpa satu pun pesan error. Aturan lama disandingkan di sini supaya niatnya
    tidak hilang lagi.
    """
    lama = {label: (cls_id in (0, 1)) for cls_id, label in URUTAN_DITUKAR.items()}
    assert lama["Ripe"] is False and lama["Unripe"] is False  # bug-nya

    baru = _keputusan(URUTAN_DITUKAR)
    assert baru[RIPE][2] is True and baru[UNRIPE][2] is True  # sudah benar


def test_tp_tidak_pernah_menembak_coil():
    """Tangkai panjang bukan janjang. Pulse untuknya = PLC menghitung buah hantu."""
    assert verdict_for_class(TP) is None


def test_jk_menembak_coil_yang_sama_dengan_unripe():
    """Piston cuma punya OK dan NG; JK ikut jalur buang, sama seperti mentah."""
    assert verdict_for_class(JK) == verdict_for_class(UNRIPE) == "REJ"


def test_model_lama_tiga_kelas_tidak_menghasilkan_satu_pun_kelas_sah():
    """Kalau MODEL_FILE masih menunjuk `best_3class_v2.pt`, tiap kotak dilewati.

    Bukan crash, dan itu memang disengaja — tapi berarti line terlihat jalan
    tanpa menghitung apa pun, jadi `model_registry` mengaduk ERROR saat startup.
    """
    lama = {0: "ACC", 1: "Rej", 2: "TP"}
    kelas = {_grade_class_or_none(v) for v in lama.values()}
    assert kelas == {None, TP}, "cuma TP yang kebetulan masih sah di model lama"


def test_label_asing_dilewati_bukan_dilempar():
    """Di loop frame 10-16 fps, melempar = grading satu line mati gara-gara satu
    kotak aneh."""
    assert _grade_class_or_none("Overripe") is None
    assert _grade_class_or_none("") is None
    assert _grade_class_or_none(None) is None


def test_log_kelas_asing_menunjuk_layar_model_deteksi(caplog):
    """Sejak model dipilih per line, `MODEL_FILE` bukan lagi satu-satunya
    tempat yang harus dicek (minor #8 review)."""
    import logging

    from palmgrade.workers import frame_processing_worker as fpw

    fpw._unknown_labels_seen.discard("KelasAneh")
    with caplog.at_level(logging.ERROR, logger=fpw.__name__):
        assert fpw._grade_class_or_none("KelasAneh") is None
    assert "Model Deteksi" in caplog.text
