"""Colour tokens of the new look (spec 2026-10-07 §4). Text colours keep the sunlight rule
of this screen: 6:1 or more against the card in both themes; tertiary text 4.5:1."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "src/palmgrade/static/console.html").read_text(encoding="utf-8")


def _token(pemilih: str) -> dict[str, str]:
    isi = re.search(re.escape(pemilih) + r"\s*\{([^}]*)\}", HTML).group(1)
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", isi)}


TERANG = _token(":root")
GELAP = _token(':root[data-theme="dark"]')


def _lum(warna: str) -> float:
    h = warna.lstrip("#")

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def kontras(a: str, b: str) -> float:
    terang, gelap = sorted((_lum(a), _lum(b)), reverse=True)
    return (terang + 0.05) / (gelap + 0.05)


@pytest.mark.parametrize("tema", [TERANG, GELAP], ids=["terang", "gelap"])
@pytest.mark.parametrize("token", ["fg", "muted", "acc", "rej", "warn", "merek", "ripe", "unripe", "jk", "tp"])
def test_warna_teks_tahan_matahari(tema, token):
    assert kontras(tema[token], tema["card"]) >= 6.0, (token, tema[token])


@pytest.mark.parametrize("tema", [TERANG, GELAP], ids=["terang", "gelap"])
def test_teks_tersier_masih_terbaca(tema):
    assert kontras(tema["muted2"], tema["card"]) >= 4.5


def test_tombol_utama_terbaca():
    for tema in (TERANG, GELAP):
        assert kontras(tema["merek-ink"], tema["merek"]) >= 4.5


def test_tema_gelap_mengisi_semua_warna_tema_terang():
    warna = {k for k, v in TERANG.items() if v.startswith(("#", "rgba"))}
    assert warna <= set(GELAP), warna - set(GELAP)


def test_tanpa_container_query_baru():
    # Lampung's kiosk Firefox version is unknown (spec §8). The one container query that
    # already shipped (Setelan, support only) stays; the new look adds none.
    assert HTML.count("@container") == 1 and HTML.count("container-type") == 1


def test_komponen_dasar_memakai_token_baru():
    assert re.search(r"button\.utama\s*\{[^}]*background:var\(--merek\)", HTML)
    assert re.search(r":focus-visible\s*\{[^}]*outline:2px solid var\(--merek\)", HTML)
    assert "outline:3px solid var(--acc)" not in HTML
    assert re.search(r"\.plat:not\(input\)\s*\{[^}]*background:var\(--plat-bg\)", HTML)
    assert re.search(r"dialog\.modal\s*\{[^}]*border-radius:var\(--r-kartu\)", HTML)
    assert re.search(r"\.panel\s*\{[^}]*border-radius:var\(--r-kartu\)", HTML)
    assert re.search(r"\.pil\s*\{[^}]*border-radius:999px", HTML)
