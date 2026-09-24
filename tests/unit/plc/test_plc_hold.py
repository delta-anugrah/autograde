"""HoldScheduler — OK/NG DITAHAN N detik, bukan pulse 200 ms (permintaan Ocit 2026-09-23).

Antarmukanya sama persis dengan PulseScheduler (enqueue / tick / dropped /
is_active) supaya PlcWorker tidak tahu mana yang dipasang. Bedanya satu:
janjang berikutnya yang datang saat coil masih ON MEMPERPANJANG tahanannya,
bukan mengantre atau dibuang — "kirim terus selama 5-10 detik" berarti selama
buah masih lewat, sinyalnya tetap ada.

Mode ini TIDAK bisa dipakai PLC untuk menghitung janjang (dua janjang berurutan
= satu sinyal panjang). Itu keputusan panel, dicatat di dokumen tim PLC.
"""
import pytest

from palmgrade.plc.hold import HoldScheduler


def _hold(hold=5.0):
    return HoldScheduler(hold_s=hold)


def test_hold_harus_positif():
    with pytest.raises(ValueError):
        HoldScheduler(hold_s=0.0)


def test_satu_permintaan_menahan_on_selama_hold_lalu_off():
    s = _hold(5.0)
    assert s.enqueue(1000) is True
    assert s.tick(now=0.0) == {1000: True}
    assert s.tick(now=4.9) == {}
    assert s.tick(now=5.0) == {1000: False}


def test_permintaan_baru_saat_masih_on_memperpanjang_bukan_mengantre():
    # Janjang kedua di detik 3 -> coil tetap ON sampai detik 8, tanpa pernah
    # turun di antaranya. Ini beda dari PulseScheduler yang akan menurunkan
    # coil lalu menyalakan lagi.
    s = _hold(5.0)
    s.enqueue(1000)
    assert s.tick(now=0.0) == {1000: True}
    s.enqueue(1000)
    assert s.tick(now=3.0) == {}          # tidak ada tepi apa pun
    assert s.tick(now=5.0) == {}          # belum turun: diperpanjang
    assert s.tick(now=8.0) == {1000: False}


def test_tidak_pernah_membuang_permintaan():
    s = _hold(5.0)
    for _ in range(50):
        assert s.enqueue(1000) is True
    assert s.dropped == 0


def test_coil_berbeda_saling_bebas():
    s = _hold(5.0)
    s.enqueue(1000)
    s.enqueue(1001)
    assert s.tick(now=0.0) == {1000: True, 1001: True}
    s.enqueue(1001)
    assert s.tick(now=5.0) == {1000: False}       # 1001 diperpanjang saat 0.0? tidak — enqueue kedua di sini
    assert s.tick(now=10.0) == {1001: False}


def test_is_active_selama_ditahan_dan_saat_menunggu_tick():
    s = _hold(5.0)
    assert s.is_active(1002) is False
    s.enqueue(1002)
    assert s.is_active(1002) is True      # sudah diminta, belum di-tick
    s.tick(now=0.0)
    assert s.is_active(1002) is True      # sedang ON
    s.tick(now=5.0)
    assert s.is_active(1002) is False     # sudah turun


def test_scheduler_diam_tidak_melapor_apa_apa():
    assert _hold().tick(now=1.0) == {}
