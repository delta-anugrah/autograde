"""Camera settings shown in the console (phase 1): the node list and the rows the line sends."""
from __future__ import annotations

from palmgrade.domain.line_tak_terbaca import SEBAB_BUKAN_LINE, SEBAB_TAK_TERJANGKAU
from palmgrade.domain.operator_error import LINE_TIDAK_MENJAWAB
from palmgrade.domain.setelan_kamera import (
    ENUM,
    FLOAT,
    INT,
    SEBAB_BUKAN_KAMERA,
    SEBAB_KAMERA_TIDAK_MENJAWAB,
    SETELAN_KAMERA,
    NilaiSetelan,
    baris_setelan,
    sebab_setelan_tak_terbaca,
)


def test_katalog_sesuai_keputusan_d1():
    """Spec §3.7: five tuning nodes editable later, the two auto modes only shown."""
    assert [(n.kunci, n.node, n.jenis, n.bisa_diubah) for n in SETELAN_KAMERA] == [
        ("exposure", "ExposureTime", FLOAT, True),
        ("gain", "Gain", FLOAT, True),
        ("black_level", "BlackLevel", INT, True),
        ("white_balance", "BalanceWhiteAuto", ENUM, True),
        ("frame_rate", "AcquisitionFrameRate", FLOAT, True),
        ("exposure_auto", "ExposureAuto", ENUM, False),
        ("gain_auto", "GainAuto", ENUM, False),
    ]


def test_baris_mengikuti_urutan_katalog_dan_membulatkan_float32():
    nilai = [
        NilaiSetelan("gain", 0.0, 0.0, 23.981199264526367),
        NilaiSetelan("exposure", 4000.0, 15.0, 9959540.0),
    ]
    baris = baris_setelan(nilai)
    assert [b["kunci"] for b in baris] == ["exposure", "gain"]
    assert baris[1] == {
        "kunci": "gain", "node": "Gain", "jenis": FLOAT, "satuan": "dB", "bisa_diubah": True,
        "didukung": True, "nilai": 0.0, "min": 0.0, "max": 23.981, "langkah": None, "pilihan": [],
    }


def test_node_yang_ditolak_tetap_satu_baris_tanpa_kode_sdk():
    """The screen says "not supported"; the SDK code stays in the line log (F6)."""
    baris = baris_setelan([NilaiSetelan("white_balance", None, kode_galat="0x80000106 (MV_E_GC_ACCESS)")])
    assert baris == [{
        "kunci": "white_balance", "node": "BalanceWhiteAuto", "jenis": ENUM, "satuan": "", "bisa_diubah": True,
        "didukung": False, "nilai": None, "min": None, "max": None, "langkah": None, "pilihan": [],
    }]


def test_enum_membawa_pilihannya():
    baris = baris_setelan([NilaiSetelan("white_balance", "Continuous", pilihan=("Off", "Once", "Continuous"))])
    assert baris[0]["nilai"] == "Continuous"
    assert baris[0]["pilihan"] == ["Off", "Once", "Continuous"]


def test_kunci_asing_dibuang():
    assert baris_setelan([NilaiSetelan("zoom", 2.0)]) == []


def test_sebab_dari_jawaban_line():
    assert sebab_setelan_tak_terbaca("line_tidak_menjawab", 409) == SEBAB_BUKAN_KAMERA
    assert sebab_setelan_tak_terbaca("line_tidak_menjawab", 503) == SEBAB_KAMERA_TIDAK_MENJAWAB
    assert sebab_setelan_tak_terbaca("line_tidak_menjawab", 404) == SEBAB_BUKAN_LINE
    assert sebab_setelan_tak_terbaca(LINE_TIDAK_MENJAWAB, None) == SEBAB_TAK_TERJANGKAU
