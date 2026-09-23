"""Line mengambil penugasan truk dari konsol saat start.

Terbukti di PC Lampung 2026-09-23: sesudah `autograde restart`, layar konsol
menampilkan `B 4400 SMA` di line 2 sementara `/health/detail` line itu menjawab
`current_assignment_id: null`. Janjang tetap digrading dan tetap masuk tabel,
tapi dengan `assignment_id` kosong — jadi tidak pernah masuk rekap per truk yang
jadi dasar bayaran. Tanpa satu pun error di layar maupun di log.

Sebabnya: penugasan cuma dikirim ke line saat operator menekan Tugaskan/Lepas
(`ConsoleService.assign_truck`). Konsol menyimpannya ke DB supaya bertahan saat
KONSOL restart, tapi tidak ada jalur yang mengirimnya ulang saat LINE restart.

Perbaikannya meniru `_tarik_setelan_grading` yang sudah ada: line yang
menanyakan, konsol yang menjawab. Arah itu penting — konsol tidak tahu kapan
sebuah line selesai boot, dan line-lah yang tahu persis kapan `RuntimeState`-nya
kosong.
"""
from __future__ import annotations

import pathlib


def _sumber_main() -> str:
    """Dibaca sebagai teks: `main.py` menarik cv2 dan torch, dan CI sengaja jalan
    tanpa keduanya (CLAUDE.md § Tests)."""
    berkas = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "palmgrade" / "main.py"
    )
    return berkas.read_text(encoding="utf-8")


def _fungsi_tarik() -> str:
    return _sumber_main().split("async def _tarik_penugasan(")[1].split("\ndef ")[0]


def _sumber_route_konsol() -> str:
    berkas = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "palmgrade" / "routes" / "console.py"
    )
    return berkas.read_text(encoding="utf-8")


def test_dipanggil_sebelum_worker_deteksi_menyala():
    """Janjang yang lewat sebelum penugasan terpasang akan tersimpan dengan
    `assignment_id` kosong — persis bug yang sedang diperbaiki. Jadi urutannya
    bagian dari perbaikan, bukan selera."""
    s = _sumber_main()
    i_state = s.index("state = get_runtime_state()")
    i_tarik = s.index("await _tarik_penugasan(settings, state)")
    i_worker = s.index("FrameProcessingWorker(")
    assert i_state < i_tarik, "state harus ada dulu"
    assert i_tarik < i_worker, "penugasan harus terpasang sebelum grading jalan"


def test_gagal_tidak_menjatuhkan_line():
    """Konsol yang belum hidup saat line start itu kejadian normal — urutan start
    container tidak dijamin. Line yang menolak start gara-gara itu jauh lebih
    buruk daripada line yang jalan tanpa truk sampai operator menugaskan."""
    f = _fungsi_tarik()
    assert "except Exception" in f
    assert "raise" not in f.split("except Exception")[1]


def test_status_bukan_200_tidak_menimpa():
    f = _fungsi_tarik()
    assert "res.status_code != 200" in f
    assert "return" in f.split("res.status_code != 200")[1][:200]


def test_line_lain_tidak_bisa_mencuri_penugasan():
    """Konsol memegang penugasan TIGA line. Line yang menanyakan harus menyebut
    machine_id-nya, dan yang dipakai harus jawaban untuk dirinya sendiri — kalau
    tidak, line 1 bisa memakai truk line 2 dan tonase mendarat di truk yang
    salah."""
    f = _fungsi_tarik()
    assert "machine_id" in f


def test_penugasan_kosong_tidak_memasang_truk_hantu():
    """Konsol menjawab untuk line yang truknya sudah Lepas dengan assignment_id
    kosong. Memasangnya apa adanya akan membuat line mengira ada truk bernama
    string kosong — `truck_folder` lalu menamai folder capture dengan potongan
    kosong dan janjang menumpuk di folder yang salah."""
    f = _fungsi_tarik()
    assert "assignment_id" in f
    # Nilai kosong harus disaring sebelum menyentuh state.
    assert "if not " in f or "or None" in f


def test_endpoint_konsol_ada_di_lane_mesin():
    """Line tidak punya sesi operator, jadi endpoint-nya harus di `ingest_router`
    (lane `x-webhook-secret`), bukan di router yang butuh login."""
    s = _sumber_route_konsol()
    assert "/internal/penugasan" in s
    blok = s.split("/internal/penugasan")[1][:800]
    assert "x_webhook_secret" in blok
    assert "401" in blok


def test_endpoint_konsol_menolak_secret_salah():
    """Tanpa ini siapa pun di LAN pabrik bisa menanyakan truk mana di line mana."""
    s = _sumber_route_konsol()
    blok = s.split("/internal/penugasan")[1][:800]
    assert "!= service.settings.webhook_secret" in blok
