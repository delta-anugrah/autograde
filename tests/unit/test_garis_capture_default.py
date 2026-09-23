"""Garis capture punya nilai awal yang berguna, bukan "tidak ada garis".

`0` bukan "belum disetel" — artinya **tidak ada garis sama sekali**, yaitu
perilaku sebelum fitur ini ada: semua janjang di dalam ROI difoto. Itu titik
awal yang salah untuk PKS baru, karena garis capture justru yang membuat
janjang difoto pada saat yang tepat, bukan saat separuhnya sudah lewat.

⚠️ `0` tetap SAH dan tetap berarti "tanpa garis" — yang berubah cuma nilai
awalnya. PKS yang memang menginginkannya harus menuliskannya sendiri.
"""
from __future__ import annotations

import re
from pathlib import Path

from palmgrade.core.config import Settings

AKAR = Path(__file__).resolve().parents[2]
COMPOSE = (AKAR / "docker-compose.yml").read_text(encoding="utf-8")
ENV_CONTOH = (AKAR / ".env.example").read_text(encoding="utf-8")

#: Titik awal yang wajar di conveyor mana pun: cukup jauh dari tepi kiri supaya
#: janjang sudah sepenuhnya masuk frame saat menyentuhnya.
BAWAAN = 200


def test_settings_bawaan_dua_ratus(monkeypatch):
    monkeypatch.delenv("GARIS_CAPTURE", raising=False)
    assert Settings().garis_capture == BAWAAN


def test_env_tetap_menang(monkeypatch):
    """Nilai awal, bukan nilai paksa: PKS yang menuliskannya tetap menang."""
    monkeypatch.setenv("GARIS_CAPTURE", "640")
    assert Settings().garis_capture == 640


def test_nol_masih_bisa_dipilih(monkeypatch):
    """⚠️ `0` tetap sah dan tetap berarti "tanpa garis". Yang berubah cuma
    nilai awalnya — bukan hilangnya pilihan itu."""
    monkeypatch.setenv("GARIS_CAPTURE", "0")
    assert Settings().garis_capture == 0


def test_compose_memakai_bawaan_yang_sama():
    """Compose punya bawaannya sendiri (`${GARIS_CAPTURE:-N}`), jadi mengubah
    `config.py` saja meninggalkan tiga line tetap pada nilai lama — dan itu
    tidak akan terlihat di mana pun."""
    cocok = re.findall(r"GARIS_CAPTURE=\$\{GARIS_CAPTURE:-(\d+)\}", COMPOSE)
    assert len(cocok) == 3, f"harap 3 line, dapat {len(cocok)}"
    assert all(int(n) == BAWAAN for n in cocok), cocok


def test_env_example_menyebut_bawaan_yang_sama():
    """Yang memasang PKS baru menyalin berkas ini; angka yang berbeda di sini
    membuat dua sumber kebenaran."""
    cocok = re.search(r"^GARIS_CAPTURE=(\d+)$", ENV_CONTOH, re.M)
    assert cocok is not None, "GARIS_CAPTURE hilang dari .env.example"
    assert int(cocok.group(1)) == BAWAAN, cocok.group(1)


def test_nol_masih_dijelaskan_di_env_example():
    """Pilihan "tanpa garis" tidak boleh hilang dari dokumentasi hanya karena
    ia bukan lagi nilai awalnya."""
    blok = ENV_CONTOH[max(0, ENV_CONTOH.index("GARIS_CAPTURE=") - 500):]
    assert "0" in blok and ("tanpa garis" in blok.lower() or "no line" in blok.lower()), blok[:300]


# ── langsung tampil di layar, tanpa perlu Simpan ────────────────────────────


def test_layar_menampilkan_bawaan_tanpa_pernah_disimpan(tmp_path, monkeypatch):
    """Yang diminta operator: angkanya sudah terisi saat konsol pertama kali
    dibuka, bukan setelah seseorang menekan Simpan.

    Konsol membaca `Settings` selama `sync_state` masih kosong, jadi mengubah
    bawaan di `config.py` sudah cukup — tapi itu perlu dibuktikan, bukan
    diasumsikan.
    """
    from palmgrade.core.config import Settings as S
    from palmgrade.repositories.console_repository import ConsoleStore
    from palmgrade.services.console_service import ConsoleService

    monkeypatch.setenv("WEBHOOK_SECRET", "uji")
    monkeypatch.delenv("GARIS_CAPTURE", raising=False)

    class _LineDiam:
        async def assign_truck(self, line, **kw): ...
        async def manual_reject(self, line, **kw): ...

    svc = ConsoleService(S(), ConsoleStore(tmp_path / "kosong.db"), _LineDiam())
    hasil = svc.setelan_grading()

    assert hasil["garis_capture"] == BAWAAN
    assert hasil["sumber"] == "env", "harus jelas ini bawaan, bukan nilai tersimpan"


def test_nilai_tersimpan_tetap_menang(tmp_path, monkeypatch):
    """Kontrol negatif: PKS yang sudah menyetel dari layar TIDAK berubah saat
    upgrade — termasuk yang sengaja memilih 0."""
    import json

    from palmgrade.core.config import Settings as S
    from palmgrade.domain.setelan_grading import KUNCI_SETELAN
    from palmgrade.repositories.console_repository import ConsoleStore
    from palmgrade.services.console_service import ConsoleService

    monkeypatch.setenv("WEBHOOK_SECRET", "uji")

    class _LineDiam:
        async def assign_truck(self, line, **kw): ...
        async def manual_reject(self, line, **kw): ...

    store = ConsoleStore(tmp_path / "terisi.db")
    store.set_state(KUNCI_SETELAN, json.dumps({
        "conf_threshold": 0.75, "minimum_size": 460000,
        "garis_capture": 0, "sumbu_garis": "tegak", "mode_dev": False,
    }))
    svc = ConsoleService(S(), store, _LineDiam())

    assert svc.setelan_grading()["garis_capture"] == 0
