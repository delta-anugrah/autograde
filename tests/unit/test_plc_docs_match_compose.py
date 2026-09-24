"""Alamat M di dokumen PLC wajib sama dengan literal docker-compose.

Dokumen ini dibaca orang yang memasang ladder: satu angka yang basi di situ
berarti LINE 1 OK jatuh di alamat LINE 1 NG. Dokumen dan compose karena itu
diikat di sini, bukan lewat niat baik.

Sumber angka di dokumen adalah komentar HTML `<!-- plc-map: ... -->` yang
tidak ikut tercetak di PDF, ditaruh tepat di bawah tabel alamat.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "docker-compose.yml"
DOCS = [REPO / "docs/plc-mc-handoff.md"]


def _compose_map() -> dict[str, list[int]]:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    lines = [services[f"ripe-line-{n}"] for n in (1, 2, 3)]
    env = [dict(item.split("=", 1) for item in svc["environment"]) for svc in lines]
    angka = lambda nilai: [int(p) for p in nilai.split(",") if p.strip()]  # noqa: E731

    def bawaan(kunci: str) -> str:
        """`${PLC_DI_BASE:-200}` -> `200`. Nilai ini diturunkan dari default
        compose, bukan dari environment mesin yang kebetulan menjalankan test."""
        nilai = env[0].get(kunci, "")
        cocok = re.fullmatch(r"\$\{[A-Z_]+:-([^}]*)\}", nilai.strip())
        return cocok.group(1) if cocok else nilai

    return {
        "base": [int(e["PLC_COIL_BASE"]) for e in env],
        "alive": sorted({n for e in env for n in angka(e.get("PLC_COIL_ALIVE", ""))}),
        "manual": sorted({n for e in env for n in angka(e.get("PLC_COIL_MANUAL", ""))}),
        "di_manual": sorted({n for e in env for n in angka(e.get("PLC_DI_MANUAL", ""))}),
        "di_base": [int(bawaan("PLC_DI_BASE"))],
        "di_count": [int(bawaan("PLC_DI_COUNT"))],
        # Literal per line sejak 2026-09-23: satu Open Setting = satu koneksi.
        "port": [int(e["PLC_PORT"]) for e in env],
    }


def _doc_map(doc: Path) -> dict[str, list[int]]:
    komentar = re.search(r"<!--\s*plc-map:(.*?)-->", doc.read_text(encoding="utf-8"), re.S)
    assert komentar, f"{doc.name} tidak punya komentar <!-- plc-map: ... -->"
    hasil = {}
    for bagian in komentar.group(1).split(";"):
        if not bagian.strip():
            continue
        kunci, nilai = bagian.split("=", 1)
        hasil[kunci.strip()] = [int(p) for p in nilai.split(",") if p.strip()]
    return hasil


def test_setiap_dokumen_plc_menyebut_alamat_yang_sama_dengan_compose():
    compose = _compose_map()
    for doc in DOCS:
        assert _doc_map(doc) == compose, f"{doc.name} tidak cocok dengan docker-compose.yml"
