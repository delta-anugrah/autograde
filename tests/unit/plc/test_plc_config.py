import os

import pytest

from palmgrade.core.config import Settings, parse_coil_list


def test_coil_offsets_derive_from_base():
    os.environ["PLC_COIL_BASE"] = "3"
    try:
        s = Settings()
        assert (s.plc_coil_ok, s.plc_coil_ng, s.plc_coil_error) == (3, 4, 5)
    finally:
        del os.environ["PLC_COIL_BASE"]


def test_plc_disabled_by_default():
    assert Settings().plc_enabled is False


def test_plc_queue_max_default_is_one():
    # Antrean pulse > 1 = staleness terakumulasi (queue_max * (pulse+gap)).
    # Sinyal yang telat menempel ke buah yang salah di belt — lebih buruk
    # daripada tidak ada sinyal. Default harus membeli staleness sesedikit mungkin.
    assert Settings().plc_queue_max == 1


def test_parse_coil_list_handles_blank_and_spaces():
    assert parse_coil_list("") == ()
    assert parse_coil_list(None) == ()
    assert parse_coil_list(" 9 , 10 ") == (9, 10)
    assert parse_coil_list("12") == (12,)


def test_parse_coil_list_degrades_to_empty_on_garbage():
    # Dulu ini raise. `PLC_COIL_ALIVE=9,10,` (koma nyantol) -> int('') -> ValueError
    # saat konstruksi Settings -> kontainer tidak pernah start. Ini knob subsistem
    # OPSIONAL yang default-nya mati, diedit operator jam 2 pagi saat commissioning:
    # typo di situ boleh mematikan bit alive, tidak boleh mematikan grading.
    assert parse_coil_list("9,abc") == ()
    assert parse_coil_list("9,10,") == ()


def test_malformed_plc_env_falls_back_to_default_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("PLC_POLL_MS", "dua ratus")
    monkeypatch.setenv("PLC_QUEUE_MAX", "")
    monkeypatch.setenv("PLC_COIL_ALIVE", "9,10,")

    s = Settings()          # tidak boleh raise

    assert s.plc_poll_ms == 200
    assert s.plc_queue_max == 1
    assert s.plc_coil_alive == ()


def test_non_plc_int_env_still_fails_fast(monkeypatch):
    # Parser toleran itu KHUSUS field PLC. Field lain tidak boleh ikut melunak.
    monkeypatch.setenv("UPLOAD_RETENTION_DAYS", "abc")
    with pytest.raises(ValueError):
        Settings()


def test_coil_manual_mati_kalau_tidak_diset():
    # Fitur piston harus mati total selama panel belum mengalokasikan coil.
    s = Settings()
    assert s.plc_coil_manual is None
    assert s.plc_di_manual is None


def test_coil_manual_dibaca_dari_env(monkeypatch):
    monkeypatch.setenv("PLC_COIL_MANUAL", "11")
    monkeypatch.setenv("PLC_DI_MANUAL", "12")
    s = Settings()
    assert (s.plc_coil_manual, s.plc_di_manual) == (11, 12)


def test_coil_manual_rusak_mematikan_fitur_bukan_grading(monkeypatch):
    monkeypatch.setenv("PLC_COIL_MANUAL", "sebelas")
    s = Settings()               # tidak boleh raise
    assert s.plc_coil_manual is None


# ── protokol: MC Protocol (langsung ke CPU) vs Modbus (lewat ODOT) ───────────


def test_protokol_bawaan_mc_protocol(monkeypatch):
    # ODOT dibatalkan 2026-09-21; jalur bawaan sekarang langsung ke CPU.
    monkeypatch.delenv("PLC_PROTOCOL", raising=False)
    assert Settings().plc_protocol == "mc"


def test_protokol_bisa_dikembalikan_ke_modbus(monkeypatch):
    monkeypatch.setenv("PLC_PROTOCOL", "modbus")
    assert Settings().plc_protocol == "modbus"


def test_protokol_tidak_dikenal_jatuh_ke_mc_bukan_crash(monkeypatch):
    # Salah ketik saat commissioning tidak boleh menahan container grading.
    monkeypatch.setenv("PLC_PROTOCOL", "modbuss")
    assert Settings().plc_protocol == "mc"


def test_protokol_tidak_peduli_huruf_besar(monkeypatch):
    monkeypatch.setenv("PLC_PROTOCOL", "  MODBUS ")
    assert Settings().plc_protocol == "modbus"


def test_port_bawaan_mengikuti_protokol(monkeypatch):
    # 1025 itu port MC Protocol yang dibuka di Open Setting GX Works2;
    # 502 itu Modbus. Bawaan yang salah = worker menelepon nomor kosong.
    monkeypatch.delenv("PLC_PORT", raising=False)
    monkeypatch.setenv("PLC_PROTOCOL", "mc")
    assert Settings().plc_port == 1025
    monkeypatch.setenv("PLC_PROTOCOL", "modbus")
    assert Settings().plc_port == 502


def test_port_eksplisit_menang_atas_bawaan_protokol(monkeypatch):
    monkeypatch.setenv("PLC_PROTOCOL", "mc")
    monkeypatch.setenv("PLC_PORT", "5007")
    assert Settings().plc_port == 5007


def test_prefix_device_bawaan_m(monkeypatch):
    monkeypatch.delenv("PLC_DEVICE_PREFIX", raising=False)
    assert Settings().plc_device_prefix == "M"


def test_prefix_device_bisa_diganti_dan_dinormalkan(monkeypatch):
    monkeypatch.setenv("PLC_DEVICE_PREFIX", " b ")
    assert Settings().plc_device_prefix == "B"


def test_di_base_bawaan_nol_dan_bisa_digeser(monkeypatch):
    # Modbus membaca discrete input mulai 0. MC Protocol membaca blok M yang
    # dialokasikan panel, jadi awalnya harus bisa digeser.
    monkeypatch.delenv("PLC_DI_BASE", raising=False)
    assert Settings().plc_di_base == 0
    monkeypatch.setenv("PLC_DI_BASE", "200")
    assert Settings().plc_di_base == 200


# ── heartbeat: MC Protocol tidak punya watchdog coupler ─────────────────────


def test_heartbeat_berkedip_secara_bawaan_di_jalur_mc(monkeypatch):
    """Tanpa ODOT tidak ada yang mereset output saat PC mati.

    Coupler dulu menjatuhkan seluruh outputnya sendiri begitu link putus
    (fault action), sehingga heartbeat level statis sudah cukup. CPU tidak
    melakukan itu: bit NG yang ditinggal ON saat PC mati akan tetap ON dan
    pistonnya menembak terus. Jadi di jalur MC heartbeat WAJIB berkedip, dan
    ladder memantau PERUBAHAN-nya — bukan levelnya.
    """
    monkeypatch.delenv("PLC_ALIVE_TOGGLE_MS", raising=False)
    monkeypatch.setenv("PLC_PROTOCOL", "mc")
    assert Settings().plc_alive_toggle_ms > 0


def test_heartbeat_tetap_level_statis_di_jalur_modbus(monkeypatch):
    # Site yang masih lewat coupler punya watchdog-nya sendiri, dan ladder
    # pak Ocit di situ membaca LEVEL. Menyalakan kedip di sana justru
    # membangkitkan alarm "PC mati" tiap setengah periode (kejadian v1.3.0).
    monkeypatch.delenv("PLC_ALIVE_TOGGLE_MS", raising=False)
    monkeypatch.setenv("PLC_PROTOCOL", "modbus")
    assert Settings().plc_alive_toggle_ms == 0


def test_heartbeat_eksplisit_menang_atas_bawaan_protokol(monkeypatch):
    monkeypatch.setenv("PLC_PROTOCOL", "mc")
    monkeypatch.setenv("PLC_ALIVE_TOGGLE_MS", "0")
    assert Settings().plc_alive_toggle_ms == 0


def test_env_plc_kosong_diam_diam_pakai_bawaan(monkeypatch, caplog):
    """`PLC_PORT=` di compose artinya "ikut bawaan", bukan salah ketik.

    Compose menulis `${PLC_PORT:-}` supaya nilainya bisa diturunkan dari
    protokol. Kalau string kosong diperlakukan seperti nilai rusak, tiga
    container meneriakkan warning palsu tiap start dan warning yang SUNGGUHAN
    (salah ketik betulan) tenggelam di antaranya.
    """
    import logging

    monkeypatch.setenv("PLC_PORT", "")
    monkeypatch.setenv("PLC_PROTOCOL", "mc")
    with caplog.at_level(logging.WARNING):
        assert Settings().plc_port == 1025
    assert "PLC_PORT" not in caplog.text


def test_env_plc_salah_ketik_tetap_berteriak(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("PLC_PORT", "seribu")
    with caplog.at_level(logging.WARNING):
        Settings()
    assert "PLC_PORT" in caplog.text
