"""Penjaga statis pita alarm PLC di console.html (tidak ada test runner JS).

Yang dijaga: pita ada di HTML, fungsinya dipanggil dari refresh(), dan tiap
kode alarm dari domain punya terjemahan di KEDUA bahasa — satu kode tanpa
terjemahan tampil sebagai kunci mentah "alarm_estop" di layar pabrik.
"""

from __future__ import annotations

import re
from pathlib import Path

from palmgrade.domain.plc_alarm import ALARM_CODES

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()


def _kamus(bahasa: str) -> str:
    kamus = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]
    blok = re.search(rf"^  {bahasa}: \{{(.*?)^  \}},", kamus, re.S | re.M)
    assert blok, f"blok bahasa {bahasa!r} tidak ditemukan"
    return blok.group(1)


def test_pita_alarm_ada_di_atas_kartu_line():
    assert HTML.index('id="pita-alarm"') < HTML.index('<div id="lines"></div>')


def test_pita_alarm_digambar_tiap_refresh():
    refresh = HTML.split("async function refresh() {", 1)[1].split("\n}\n", 1)[0]
    assert "gambarPitaAlarm(s.lines)" in refresh


def test_setiap_kode_alarm_diterjemahkan_di_kedua_bahasa():
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        hilang = [c for c in ALARM_CODES if f"alarm_{c}:" not in isi]
        assert not hilang, f"KAMUS.{bahasa} belum menerjemahkan {hilang}"


def test_pita_alarm_memakai_esc_bukan_innerhtml_mentah():
    fn = HTML.split("function gambarPitaAlarm(", 1)[1].split("\n}\n", 1)[0]
    assert "esc(" in fn


def test_uji_plc_memberi_nama_bit():
    fn = HTML.split("function isiDiPlc(", 1)[1].split("\n}\n", 1)[0]
    assert "namaBitPlc(" in fn
    for bahasa in ("id", "en"):
        isi = _kamus(bahasa)
        for kunci in ("diMotor:", "diEstop:", "diKosong:"):
            assert kunci in isi, f"KAMUS.{bahasa} tanpa {kunci}"
