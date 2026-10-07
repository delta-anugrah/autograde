"""Batch 4.6: may the staged version be installed now? Pure rules, no files, no server."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from palmgrade.domain import pembaruan as p
from palmgrade.domain.operator_error import CODES

WIB = timezone(timedelta(hours=7))
JAM = datetime(2026, 10, 20, 8, 0, tzinfo=WIB)
STATUS_SIAP = '{"schema": 1, "installed": "v1.22.0", "staged": "v1.22.1", "checked_at": "2026-10-20T07:00:00+07:00", "watcher": true}'


def _permintaan(id_="r-1", target="v1.22.1", menit_lalu=1):
    return p.Permintaan(id=id_, target=target, at=JAM - timedelta(minutes=menit_lalu))


def _hasil(state, id_="r-1", target="v1.22.1", installed="v1.22.0", menit_lalu=0):
    return p.Hasil(id=id_, state=state, target=target, installed=installed, at=JAM - timedelta(minutes=menit_lalu))


def _keadaan(status=STATUS_SIAP, permintaan=None, hasil=None, jalan="v1.22.0"):
    return p.keadaan_pembaruan(p.urai_status(status), permintaan, hasil, jalan, JAM)


def test_kunci_versi_cuma_menerima_rilis_resmi():
    assert p.kunci_versi("v1.22.1") == (1, 22, 1)
    assert p.kunci_versi("v1.22.1-cpu") == (1, 22, 1)
    # Tag sementara 4.2 dan teks asing tidak pernah dianggap versi.
    for teks in (None, "", "latest", "unknown", "1.22.1", "v1.22", "v1.22.1-uji-abc123"):
        assert p.kunci_versi(teks) is None, teks


def test_lebih_baru_membandingkan_angka_bukan_huruf():
    assert p.lebih_baru("v1.22.10", "v1.22.9")
    assert not p.lebih_baru("v1.22.1", "v1.22.1")
    assert not p.lebih_baru("v1.21.9", "v1.22.0")
    assert not p.lebih_baru("v1.22.1", "unknown")


def test_status_rusak_atau_skema_lain_dianggap_tidak_ada():
    for teks in (None, "", "{", "[]", '{"schema": 2, "staged": "v1.22.1", "watcher": true}'):
        assert p.urai_status(teks) is None, teks


def test_versi_baru_ditawarkan():
    k = _keadaan()
    assert (k.terpasang, k.siap, k.berjalan, k.hasil) == (True, "v1.22.1", False, None)


def test_staged_sama_atau_lebih_tua_dari_yang_jalan_tidak_ditawarkan():
    # Teknisi sudah `autograde pull`: berkas status masih menyebut v1.22.1.
    assert _keadaan(jalan="v1.22.1").siap is None
    assert _keadaan(jalan="v1.23.0").siap is None


def test_penunggu_belum_dipasang_tidak_menawarkan_apa_pun():
    tanpa = STATUS_SIAP.replace('"watcher": true', '"watcher": false')
    assert _keadaan(status=tanpa).terpasang is False
    assert _keadaan(status=tanpa).siap is None
    assert _keadaan(status=None).terpasang is False


def test_penanda_tanpa_jawaban_berarti_berjalan():
    k = _keadaan(permintaan=_permintaan(), hasil=_hasil("running"))
    assert k.berjalan is True
    assert k.siap is None


def test_penanda_basi_dianggap_gagal_dan_boleh_ditekan_lagi():
    k = _keadaan(permintaan=_permintaan(menit_lalu=21))
    assert k.berjalan is False
    assert k.hasil["state"] == "timeout"
    assert k.siap == "v1.22.1"


def test_hasil_ok_ditampilkan_sesudah_konsol_hidup_lagi():
    k = _keadaan(permintaan=_permintaan(), hasil=_hasil("ok", installed="v1.22.1"), jalan="v1.22.1")
    assert k.berjalan is False
    assert k.hasil == {"state": "ok", "target": "v1.22.1", "installed": "v1.22.1", "at": "2026-10-20T08:00:00+07:00"}


def test_versi_yang_gagal_gerbang_tidak_ditawarkan_lagi():
    k = _keadaan(permintaan=_permintaan(), hasil=_hasil("rolled_back"))
    assert k.siap is None
    assert k.hasil["state"] == "rolled_back"


def test_failed_berarti_belum_dicoba_jadi_ditawarkan_lagi():
    # Launcher menulis `failed` kalau versi baru TIDAK dicoba (kunci dipegang proses
    # lain, promote dilewat, launcher berhenti di tengah). Versinya tidak terbukti rusak.
    k = _keadaan(permintaan=_permintaan(), hasil=_hasil("failed"))
    assert k.siap == "v1.22.1"
    assert k.hasil["state"] == "failed"


def test_hasil_lama_tidak_ditampilkan():
    k = _keadaan(permintaan=_permintaan(menit_lalu=60 * 25), hasil=_hasil("ok", menit_lalu=60 * 25), jalan="v1.22.0")
    assert k.hasil is None


def test_line_bertruk_cuma_yang_truck_id_terisi():
    assignments = {
        "L3": {"truck_id": "T-9"},
        "L1": {"truck_id": "T-1"},
        "L2": {"truck_id": None},
        "L4": {"truck_id": ""},
    }
    assert p.line_bertruk(assignments) == ["L1", "L3"]


def test_boleh_pasang_menolak_dengan_kode_yang_bisa_dibaca_layar():
    with pytest.raises(p.PembaruanAdaTruk) as e:
        p.boleh_pasang(_keadaan(), "v1.22.1", ["L1", "L3"])
    assert e.value.as_detail()["code"] == "pembaruan_ada_truk"
    assert e.value.as_detail()["params"] == {"line": "L1, L3"}

    with pytest.raises(p.PembaruanBerjalan):
        p.boleh_pasang(_keadaan(permintaan=_permintaan()), "v1.22.1", [])
    with pytest.raises(p.PembaruanTidakAda):
        p.boleh_pasang(_keadaan(), "v1.99.0", [])
    with pytest.raises(p.PembaruanBelumTerpasang):
        p.boleh_pasang(_keadaan(status=None), "v1.22.1", [])


def test_boleh_pasang_lolos_tanpa_truk():
    assert p.boleh_pasang(_keadaan(), "v1.22.1", []) is None


def test_isi_permintaan_sesuai_kontrak():
    assert p.isi_permintaan("r-9", "v1.22.1", "op@pks.test", JAM) == {
        "schema": 1,
        "id": "r-9",
        "target": "v1.22.1",
        "by": "op@pks.test",
        "at": "2026-10-20T08:00:00+07:00",
    }


def test_kode_baru_terdaftar():
    for kode in (
        "pembaruan_ada_truk",
        "pembaruan_tidak_ada",
        "pembaruan_berjalan",
        "pembaruan_belum_terpasang",
        "pembaruan_lepas_gagal",
    ):
        assert kode in CODES


def test_lepas_gagal_menyebut_line_yang_tidak_menjawab():
    detail = p.PembaruanLepasGagal("L2").as_detail()
    assert detail["code"] == "pembaruan_lepas_gagal"
    assert detail["params"] == {"line": "L2"}


def test_versi_lebih_baru_sesudah_rollback_ditawarkan_lagi():
    # Keputusan user 2026-10-02: versi yang rolled_back disembunyikan sampai ada versi
    # yang LEBIH BARU di-stage, bukan menunggu teknisi atau jeda waktu.
    lebih_baru = STATUS_SIAP.replace('"staged": "v1.22.1"', '"staged": "v1.22.2"')
    k = _keadaan(status=lebih_baru, permintaan=_permintaan(), hasil=_hasil("rolled_back"))
    assert k.siap == "v1.22.2"
    assert k.hasil["state"] == "rolled_back"


def test_rollback_tetap_disembunyikan_walau_sudah_lewat_sehari():
    # Kartu hasil hilang sesudah 24 jam, tapi versi yang gagal tetap tidak ditawarkan.
    k = _keadaan(permintaan=_permintaan(menit_lalu=60 * 30), hasil=_hasil("rolled_back", menit_lalu=60 * 30))
    assert k.hasil is None
    assert k.siap is None


def test_hasil_dari_permintaan_lain_diabaikan():
    k = _keadaan(permintaan=_permintaan(id_="r-2"), hasil=_hasil("ok", id_="r-1"))
    assert k.berjalan is True
    assert k.hasil is None


def test_permintaan_rusak_dianggap_tidak_ada():
    for teks in (
        None,
        "{",
        '{"schema": 1, "id": "", "target": "v1.22.1", "at": "2026-10-20T08:00:00+07:00"}',
        '{"schema": 1, "id": "r", "target": "latest", "at": "2026-10-20T08:00:00+07:00"}',
        '{"schema": 1, "id": "r", "target": "v1.22.1", "at": "2026-10-20T08:00:00"}',
    ):
        assert p.urai_permintaan(teks) is None, teks


def test_hasil_kontrak_launcher_terurai():
    # Persis bentuk yang ditulis `tulis_hasil` di autograde.sh (sawit).
    teks = (
        '{"schema": 1, "id": "r-1", "state": "rolled_back", "target": "v1.22.1", '
        '"installed": "v1.22.0", "at": "2026-10-20T08:05:00+07:00"}'
    )
    h = p.urai_hasil(teks)
    assert (h.id, h.state, h.target, h.installed) == ("r-1", "rolled_back", "v1.22.1", "v1.22.0")
    assert p.urai_hasil(teks.replace("rolled_back", "aneh")) is None


# ── log line for the Log tab (user decision 4: outcome on screen and in the Log tab) ──


def test_baris_log_hasil_gagal_naik_error_berhasil_warning():
    def h(state, installed="v1.22.0"):
        return {"state": state, "target": "v1.22.1", "installed": installed, "at": "2026-10-20T08:04:00+07:00"}

    assert p.baris_log_hasil(h("ok", "v1.22.1"))[0] == "WARNING"
    assert p.baris_log_hasil(h("nothing"))[0] == "WARNING"
    for state in ("rolled_back", "failed", "timeout"):
        level, pesan = p.baris_log_hasil(h(state))
        assert level == "ERROR", state
        assert "v1.22.1" in pesan, state
    assert "v1.22.0" in p.baris_log_hasil(h("rolled_back"))[1]
    assert p.baris_log_hasil(None) is None
    assert p.baris_log_hasil(h("running")) is None
