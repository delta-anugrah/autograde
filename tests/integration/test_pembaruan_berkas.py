"""Batch 4.6: the console side of the update files, on a real folder."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from palmgrade.domain.pembaruan import PembaruanAdaTruk, PembaruanBelumTerpasang, PembaruanBerjalan
from palmgrade.services.pembaruan_service import HASIL, PERMINTAAN, STATUS, PembaruanService

WIB = timezone(timedelta(hours=7))
JAM = datetime(2026, 10, 20, 8, 0, tzinfo=WIB)


def _status(folder, staged="v1.22.1", watcher=True):
    (folder / STATUS).write_text(
        json.dumps(
            {
                "schema": 1,
                "installed": "v1.22.0",
                "staged": staged,
                "checked_at": "2026-10-20T07:00:00+07:00",
                "watcher": watcher,
            }
        )
    )


@pytest.fixture
def svc(tmp_path):
    nomor = iter(f"r-{i}" for i in range(1, 100))
    return PembaruanService(tmp_path, lambda: "v1.22.0", lambda: JAM, buat_id=lambda: next(nomor))


def test_folder_tidak_ada_berarti_belum_terpasang(tmp_path):
    svc = PembaruanService(tmp_path / "tidak-ada", lambda: "v1.22.0", lambda: JAM)
    assert svc.keadaan().terpasang is False
    with pytest.raises(PembaruanBelumTerpasang):
        svc.pasang("v1.22.1", [], "op@pks.test")
    assert not (tmp_path / "tidak-ada").exists()


def test_status_setengah_tertulis_tidak_membuat_crash(tmp_path, svc):
    (tmp_path / STATUS).write_text('{"schema": 1, "staged": "v1.2')
    assert svc.keadaan().terpasang is False


def test_pasang_menulis_penanda_sesuai_kontrak(tmp_path, svc):
    _status(tmp_path)
    assert svc.pasang("v1.22.1", [], "op@pks.test") == {"id": "r-1", "target": "v1.22.1"}
    assert json.loads((tmp_path / PERMINTAAN).read_text()) == {
        "schema": 1,
        "id": "r-1",
        "target": "v1.22.1",
        "by": "op@pks.test",
        "at": "2026-10-20T08:00:00+07:00",
    }
    # Atomic: no temp file left behind for the watcher to trip on.
    assert sorted(p.name for p in tmp_path.iterdir()) == [PERMINTAAN, STATUS]
    assert svc.sedang_berjalan() is True


def test_ada_truk_tidak_menulis_apa_pun(tmp_path, svc):
    _status(tmp_path)
    with pytest.raises(PembaruanAdaTruk):
        svc.pasang("v1.22.1", ["L2"], "op@pks.test")
    assert not (tmp_path / PERMINTAAN).exists()


def test_tekan_kedua_ditolak_sampai_hasil_final(tmp_path, svc):
    _status(tmp_path)
    svc.pasang("v1.22.1", [], "op@pks.test")
    with pytest.raises(PembaruanBerjalan):
        svc.pasang("v1.22.1", [], "sp@pks.test")
    (tmp_path / HASIL).write_text(
        json.dumps(
            {
                "schema": 1,
                "id": "r-1",
                "state": "ok",
                "target": "v1.22.1",
                "installed": "v1.22.1",
                "at": "2026-10-20T08:03:00+07:00",
            }
        )
    )
    keadaan = svc.keadaan()
    assert keadaan.berjalan is False
    assert keadaan.hasil["state"] == "ok"


def test_dua_tekanan_bersamaan_cuma_satu_penanda(tmp_path, svc):
    _status(tmp_path)
    hasil, salah = [], []

    def tekan():
        try:
            hasil.append(svc.pasang("v1.22.1", [], "op@pks.test"))
        except PembaruanBerjalan as exc:
            salah.append(exc)

    benang = [threading.Thread(target=tekan) for _ in range(5)]
    for b in benang:
        b.start()
    for b in benang:
        b.join()
    assert (len(hasil), len(salah)) == (1, 4)


def test_berkas_hasil_launcher_dibaca_balik(tmp_path, svc):
    # Bentuk persis `tulis_hasil` di autograde.sh: rollback = versi itu tidak ditawarkan lagi.
    _status(tmp_path)
    svc.pasang("v1.22.1", [], "op@pks.test")
    (tmp_path / HASIL).write_text(
        '{"schema": 1, "id": "r-1", "state": "rolled_back", "target": "v1.22.1", '
        '"installed": "v1.22.0", "at": "2026-10-20T08:04:00+07:00"}\n'
    )
    keadaan = svc.keadaan()
    assert (keadaan.berjalan, keadaan.siap, keadaan.hasil["state"]) == (False, None, "rolled_back")


def test_status_dari_launcher_dibaca(tmp_path, svc):
    # Bentuk persis `tulis_status` di autograde.sh (satu baris, diakhiri newline).
    (tmp_path / STATUS).write_text(
        '{"schema": 1, "installed": "v1.22.0", "staged": "v1.22.1", '
        '"checked_at": "2026-10-20T07:00:00+07:00", "watcher": true}\n'
    )
    keadaan = svc.keadaan()
    assert (keadaan.terpasang, keadaan.siap) == (True, "v1.22.1")


def _hasil_rollback(folder):
    (folder / HASIL).write_text(
        '{"schema": 1, "id": "r-1", "state": "rolled_back", "target": "v1.22.1", '
        '"installed": "v1.22.0", "at": "2026-10-20T08:04:00+07:00"}\n'
    )


def _baris(caplog, level):
    return [r for r in caplog.records if r.name.endswith("pembaruan_service") and r.levelname == level]


def test_permintaan_tercatat_di_tab_log_dengan_nama_penekan(tmp_path, svc, caplog):
    # The Log tab stores WARNING and above only (SqliteLogHandler).
    _status(tmp_path)
    svc.pasang("v1.22.1", [], "op@pks.test")
    assert any("op@pks.test" in r.getMessage() for r in _baris(caplog, "WARNING"))


def test_hasil_tercatat_sekali_walau_konsol_restart(tmp_path, svc, caplog):
    _status(tmp_path)
    svc.pasang("v1.22.1", [], "op@pks.test")
    _hasil_rollback(tmp_path)
    svc.keadaan()
    svc.keadaan()
    # The install restarts the console: a new process reads the same result.json.
    PembaruanService(tmp_path, lambda: "v1.22.0", lambda: JAM).keadaan()
    error = _baris(caplog, "ERROR")
    assert len(error) == 1, [r.getMessage() for r in error]
    assert "v1.22.1" in error[0].getMessage()


def test_folder_hanya_baca_tetap_mencatat_tanpa_crash(tmp_path, svc, caplog, monkeypatch):
    _status(tmp_path)
    svc.pasang("v1.22.1", [], "op@pks.test")
    _hasil_rollback(tmp_path)

    def menolak(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(svc, "_tulis_atomik", menolak)
    assert svc.keadaan().hasil["state"] == "rolled_back"
    svc.keadaan()
    assert len(_baris(caplog, "ERROR")) == 1


# ── assign and install: no gap, but no queue behind a slow line (review 2026-10-03) ──


def test_assign_di_line_lain_tidak_antre_di_belakang_line_yang_lambat(tmp_path, svc):
    """The line call can take 10 s (dead line): it must not run under the shared lock."""
    _status(tmp_path)

    async def jalan():
        masuk_keduanya = asyncio.Event()
        di_dalam = []

        async def tugaskan(line):
            async with svc.menugaskan(line):
                di_dalam.append(line)
                if len(di_dalam) == 2:
                    masuk_keduanya.set()
                await asyncio.wait_for(masuk_keduanya.wait(), 1)

        await asyncio.gather(tugaskan("line-1"), tugaskan("line-2"))

    asyncio.run(jalan())


def test_install_melihat_line_yang_assign_nya_belum_dijawab(tmp_path, svc):
    _status(tmp_path)

    async def jalan():
        async with svc.menugaskan("line-2"):
            assert not svc.kunci.locked()
            assert svc.line_sedang_ditugaskan() == ["line-2"]
        assert svc.line_sedang_ditugaskan() == []

    asyncio.run(jalan())


def test_assign_ditolak_selama_pemasangan_berjalan(tmp_path, svc):
    _status(tmp_path)
    svc.pasang("v1.22.1", [], "op@pks.test")

    async def jalan():
        async with svc.menugaskan("line-1"):
            pass

    with pytest.raises(PembaruanBerjalan):
        asyncio.run(jalan())
    assert svc.line_sedang_ditugaskan() == []
