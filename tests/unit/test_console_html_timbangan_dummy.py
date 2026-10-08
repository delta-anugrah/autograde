"""Dummy scale on the screen (2026-10-07): an orange band on every tab while it is on, and a
switch with its own Simpan in Settings > Developer Mode."""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text(
    encoding="utf-8"
)
KAMUS = HTML.split("const KAMUS = {", 1)[1].split("\n};", 1)[0]


def _fungsi(nama: str) -> str:
    mulai = re.search(rf"(async )?function {nama}\(", HTML).start()
    return HTML[mulai : HTML.index("\n}\n", mulai)]


def _bahasa(kode: str) -> str:
    return re.search(rf"^  {kode}: \{{(.*?)^  \}},", KAMUS, re.S | re.M).group(1)


def test_pita_dummy_mengikuti_polling():
    assert 'id="pita-dummy"' in HTML
    assert "gambarPitaDummy(s.timbangan_dummy === true)" in _fungsi("refresh")


def test_saklar_dummy_di_mode_developer_dan_kamus_dua_bahasa():
    # One Save on Developer Mode (owner 2026-10-08): the main Simpan also saves the dummy switch.
    assert 'id="set-dummy"' in HTML and 'id="set-dummy-simpan"' not in HTML
    assert '"/api/console/dev/timbangan-dummy"' in _fungsi("muatDummy")
    assert "await muatDummy();" in HTML
    for kunci in ("lbTimbanganDummy", "pitaTimbanganDummy", "dummyTersimpan", "timbangDummy"):
        assert kunci in _bahasa("id") and kunci in _bahasa("en")


def test_kotak_timbangan_menyebut_dummy_bukan_belum_tersambung():
    assert '"timbangDummy"' in _fungsi("gambarTimbanganLive")


def test_the_main_save_also_saves_the_dummy_switch_when_it_changed():
    simpan = HTML.split('$("set-simpan").addEventListener', 1)[1].split("\n}));", 1)[0]
    assert '"/api/console/dev/timbangan-dummy"' in simpan
    assert '$("set-dummy").checked !== dummyTersimpanNilai' in simpan
    assert "dummyTersimpanNilai = Boolean(r.aktif)" in _fungsi("muatDummy")
