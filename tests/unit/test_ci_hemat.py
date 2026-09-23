"""CI dijaga tetap murah — repo ini PRIVATE, jadi setiap menit ditagih.

Diukur pada 40 run terakhir (2026-09-22): 68 menit total, dan jatahnya habis di
tengah hari kerja sampai CI berhenti jalan sama sekali. Yang dijaga di sini
bukan kecepatan demi kecepatan, tapi bahwa penghematan yang sudah dipasang
tidak hilang diam-diam saat workflow-nya disunting lagi.

⚠️ Yang TIDAK boleh dipotong ada di `test_e2e_tetap_dijalankan`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

AKAR = Path(__file__).resolve().parents[2]
CI_TEKS = (AKAR / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
# `on:` diparse YAML jadi True (kata kunci YAML 1.1), jadi kuncinya dicari
# lewat `True` maupun `"on"`.
CI = yaml.safe_load(CI_TEKS)
DEPLOY_TEKS = (AKAR / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
TRELLO_TEKS = (AKAR / ".github" / "workflows" / "trello-move-in-review.yml").read_text(
    encoding="utf-8"
)


def _pemicu(doc: dict) -> dict:
    return doc.get("on") or doc.get(True) or {}


# ── satu commit diuji sekali ────────────────────────────────────────────────


def test_push_hanya_dijaga_di_main():
    """PR ke `staging` sudah diuji; menjalankannya lagi saat merge menguji
    commit yang sama persis dan membayar dua kali.

    `main` tetap dijaga karena itu yang menuju pabrik, dan merge ke sana bisa
    membawa penyelesaian konflik yang belum pernah diuji sebagai satu kesatuan.
    """
    push = _pemicu(CI).get("push") or {}
    assert push.get("branches") == ["main"], push


def test_pull_request_tetap_menguji_keduanya():
    """Kontrol negatif: yang dibuang trigger `push` ke staging, BUKAN
    pengujian PR-nya. Tanpa ini, perubahan di atas akan membuat staging tidak
    terjaga sama sekali."""
    pr = _pemicu(CI).get("pull_request") or {}
    assert set(pr.get("branches") or []) == {"staging", "main"}, pr


# ── `paths-ignore` sengaja TIDAK dipakai ────────────────────────────────────


def test_tidak_ada_paths_ignore_untuk_docs():
    """⚠️ Terlihat seperti penghematan gratis, dan di repo ini BUKAN.

    Diperiksa 2026-09-22: `tests/unit/test_doc_links.py` membaca
    `docs/**/*.md` lewat `rglob` untuk membuktikan tiap jalur yang disebut
    dokumen benar-benar ada — termasuk `docs/runbooks/`. Delapan berkas docs
    lain juga punya test isinya sendiri (`MANUAL.md`, `ONBOARDING.md`,
    `SETUP.md`, `overview.md`, `plc-*.md`, `camera-spec.md`,
    `autograde-integration.md`).

    Jadi PR yang cuma menyunting dokumen justru YANG PALING PERLU diuji: itu
    satu-satunya perubahan yang bisa memerahkan test-test itu. Mengabaikannya
    akan membuat tautan mati lolos tanpa ada yang tahu.
    """
    for blok in ("pull_request", "push"):
        isi = _pemicu(CI).get(blok) or {}
        assert "paths-ignore" not in isi, f"{blok}: lihat docstring"
        assert "paths" not in isi, f"{blok}: lihat docstring"


# ── cache ───────────────────────────────────────────────────────────────────


def test_pip_di_cache():
    """~14 wheel diunduh ulang tiap run, termasuk opencv-headless (~35 MB)."""
    assert "cache: 'pip'" in CI_TEKS or 'cache: "pip"' in CI_TEKS or "cache: pip" in CI_TEKS


def test_daftar_paket_punya_berkas_sendiri():
    """`cache: pip` butuh berkas yang bisa di-hash sebagai kunci; daftar paket
    yang cuma hidup di baris `run:` tidak bisa dipakai."""
    assert (AKAR / "requirements-ci.txt").is_file()


def test_build_image_memakai_cache_registry():
    """Cache GHA tidak dipakai dengan sengaja — layer CUDA + torch lebih besar
    dari batas 10 GB dan akan mengusir dirinya sendiri tiap run (alasan
    aslinya ada di komentar workflow, dan masih berlaku).

    Registry cache tidak punya batas itu: layernya duduk di GHCR bersama
    image-nya sendiri.
    """
    assert "type=registry" in DEPLOY_TEKS, "build masih tanpa cache sama sekali"
    assert "cache-from:" in DEPLOY_TEKS
    assert "cache-to:" in DEPLOY_TEKS


def test_cache_tidak_memakai_gha():
    """Kontrol negatif terhadap alasan di atas: `type=gha` akan mengembalikan
    persis masalah yang membuat cache dimatikan.

    Yang diperiksa baris `cache-from:`/`cache-to:` saja — komentar BOLEH
    menyebut `type=gha`, dan memang menyebutnya untuk menjelaskan kenapa ia
    tidak dipakai.
    """
    baris_cache = [
        b.strip()
        for b in DEPLOY_TEKS.splitlines()
        if b.strip().startswith(("cache-from:", "cache-to:"))
    ]
    assert baris_cache, "tidak ada baris cache sama sekali"
    for b in baris_cache:
        assert "type=gha" not in b, b


# ── yang tidak boleh dipotong ───────────────────────────────────────────────


def test_e2e_tetap_dijalankan():
    """⚠️ JANGAN dibuang untuk menghemat 40 detik.

    Suite ini menjaga jalur yang menggerakkan uang dan besi: sinkron ERP, scan
    QR gerbang, rekonsiliasi truk, pemicu coil PLC. Dulu tidak di-CI, dan
    regresi jalur timbang-keluar lolos ke staging lalu merah SEHARI PENUH
    sebelum ada yang sadar (#96).
    """
    assert "pytest tests/e2e/" in CI_TEKS


def test_e2e_melaporkan_alasan_skip():
    """`-rs` mencetak kenapa tiap test melewati dirinya. Tanpa itu, suite yang
    diam-diam berhenti menjalankan apa pun tetap melapor sukses — kegagalan
    yang justru dicegah oleh adanya langkah ini."""
    assert "pytest tests/e2e/ -rs" in CI_TEKS


def test_lint_dan_unit_tetap_ada():
    assert "ruff check" in CI_TEKS
    assert "pytest tests/unit/" in CI_TEKS
