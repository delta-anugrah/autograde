"""Integrasi tab Riwayat: jalur pabrik yang sungguhan sampai ke baris di layar.

- Janjang masuk lewat `ConsoleService.ingest` (payload kontrak §5 dari line), jadi
  `work_date` dihitung aturan hari kerja yang asli: janjang 01:30 WIB masuk hari
  kerja yang sama dengan shift-nya, bukan tanggal UTC.
- Tiket timbang lewat `ConsoleService.record_weighing` (jalur tombol Timbang masuk),
  jadi neto dihitung, bukan dipercaya.
- `RiwayatService` membaca console.db yang SAMA lewat koneksinya sendiri, dan angka
  satu hari harus sama dengan tab Rekap (`ConsoleService.recap`).
- Baris yang dijawab server digambar oleh fungsi di `console.html` lewat node.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from palmgrade.core.config import Settings
from palmgrade.repositories.console_repository import ConsoleStore
from palmgrade.repositories.riwayat_repository import RiwayatStore
from palmgrade.services.console_service import ConsoleService
from palmgrade.services.riwayat_service import RiwayatService

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text()
NODE = shutil.which("node")


class _LineDiam:
    """Line yang tidak pernah dipanggil di test ini."""


@pytest.fixture
def pabrik(tmp_path):
    settings = replace(Settings(), factory_tz="Asia/Jakarta")
    db = tmp_path / "console.db"
    konsol = ConsoleService(settings, ConsoleStore(db), _LineDiam())
    riwayat = RiwayatService(RiwayatStore(db), hari_ini=lambda: "2026-09-26", zona="Asia/Jakarta")
    return konsol, riwayat


def _janjang(konsol, nomor, ts, status="ACC", kelas="Ripe", truk=None):
    return konsol.ingest({
        "event_id": f"ev-{nomor}", "machine_id": konsol.lines[0].machine_id, "timestamp": ts,
        "ripeness_status": status, "prediction": "Acc" if status == "ACC" else "Rej",
        "grade_class": kelas, "ripeness_confidence": 0.9, "capture_type": "auto",
        "image_path": f"captures/results/x/{nomor}.webp", "truck_id": truk, "assignment_id": None,
    })


def test_satu_hari_riwayat_sama_dengan_rekap_dan_jam_malam_ikut_hari_kerjanya(pabrik):
    konsol, riwayat = pabrik
    truk = konsol.register_manual_truck("BE 1234 AB")["id"]
    hari = [
        _janjang(konsol, 1, "2026-09-24T01:00:00+00:00", truk=truk),                 # 08:00 WIB
        _janjang(konsol, 2, "2026-09-24T02:00:00+00:00", "REJ", "JK", truk=truk),    # 09:00 WIB
        _janjang(konsol, 3, "2026-09-24T18:30:00+00:00", truk=truk),                 # 01:30 WIB tgl 25
        _janjang(konsol, 4, "2026-09-25T03:00:00+00:00", "REJ", "Unripe", truk=truk),
    ]
    asyncio.run(konsol.record_weighing({
        "plate_number": "BE 1234 AB", "gross_kg": 12000, "tare_kg": 4500,
        "entered_at": "2026-09-24T08:00:00+07:00",
    }))

    f = riwayat.filter(dari="2026-09-20", sampai="2026-09-26")
    per_hari = riwayat.halaman(f, tampilan="hari", limit=25, offset=0, ringkasan=True)

    tanggal = {h["work_date"]: h for h in per_hari["items"]}
    assert set(tanggal) == set(hari)
    for hari_kerja, baris in tanggal.items():
        rekap = konsol.recap(hari_kerja)
        assert baris["total"] == sum(r["total"] for r in rekap)
        assert baris["jk"] == sum(r["jk"] for r in rekap)
        assert baris["neto_kg"] == (sum(r["net_kg"] for r in rekap if r["net_kg"] is not None) or None)
    assert per_hari["ringkasan"]["total"] == 4
    assert per_hari["ringkasan"]["neto_kg"] == 7500.0


@pytest.mark.skipif(NODE is None, reason="node tidak ada")
def test_baris_dari_jawaban_sungguhan_tergambar_di_layar(pabrik):
    konsol, riwayat = pabrik
    truk = konsol.register_manual_truck("BE 1234 AB")["id"]
    _janjang(konsol, 1, "2026-09-24T01:00:00+00:00", truk=truk)
    _janjang(konsol, 2, "2026-09-24T02:00:00+00:00", "REJ", "JK", truk=truk)
    f = riwayat.filter(dari="2026-09-24", sampai="2026-09-24")
    per_truk = riwayat.halaman(f, tampilan="truk", limit=25, offset=0, ringkasan=False)["items"]
    per_janjang = riwayat.halaman(f, tampilan="janjang", limit=25, offset=0, ringkasan=False)["items"]

    def fungsi(nama: str) -> str:
        awal = HTML.index(f"function {nama}(")
        return HTML[awal : HTML.index("\n}", awal) + 2]

    skrip = (
        'const esc = (s) => String(s ?? "").replace(/[&<>"\'`]/g, (c) =>'
        ' ({ "&":"&amp;","<":"&lt;",">":"&gt;",\'"\':"&quot;","\'":"&#39;","`":"&#96;" }[c]));\n'
        'const KOSONG = "-"; const t = (k) => k; const lokal = () => "id-ID";\n'
        'const dash = (v) => (v === null || v === undefined || v === "" ? KOSONG : esc(v));\n'
        'const kg = (v) => (v === null || v === undefined ? KOSONG : Number(v).toLocaleString(lokal()));\n'
        'const tagHasil = (s, kelas) => `<span class="tag">${esc(kelas || s)}</span>`;\n'
        'const waktu = (iso) => String(iso); let riwayatOffset = 0;\n'
        + "\n".join(fungsi(n) for n in ("tanggalRiwayat", "rasioRiwayat", "barisRiwayatTruk",
                                        "barisRiwayatJanjang"))
        + f"\nconsole.log(JSON.stringify([{json.dumps(per_truk)}.map(barisRiwayatTruk),"
        + f" {json.dumps(per_janjang)}.map(barisRiwayatJanjang)]));"
    )
    hasil = subprocess.run([NODE, "-e", skrip], capture_output=True, text=True, timeout=30)
    assert hasil.returncode == 0, hasil.stderr[-800:]
    truk_html, janjang_html = json.loads(hasil.stdout)

    assert len(truk_html) == 1 and "BE 1234 AB" in truk_html[0] and ">50%<" in truk_html[0]
    assert len(janjang_html) == 2
    assert all('class="foto"' in b and "/captures/line-1/" in b for b in janjang_html)
