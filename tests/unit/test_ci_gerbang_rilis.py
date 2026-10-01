"""Image rilis hanya dibangun sesudah CI hijau di commit tag yang sama (batch 4.1).

Terbukti di v1.18.0: build image mulai 10 detik sesudah CI mulai, jadi image dari commit
yang test-nya merah bisa terbit dan ditarik PC pabrik. `deploy.yml` sekarang memanggil
`ci.yml` sebagai job dan kedua build (pabrik dan demo `-cpu`) menunggu job itu.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _muat(nama: str) -> dict:
    return yaml.safe_load((WORKFLOWS / nama).read_text(encoding="utf-8"))


def _pemicu(doc: dict) -> dict:
    # YAML 1.1 membaca kunci `on:` sebagai True.
    return doc.get("on") or doc.get(True) or {}


def _needs(job: dict) -> list[str]:
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


CI = _muat("ci.yml")
DEPLOY = _muat("deploy.yml")
DEMO = _muat("demo-image.yml")
CI_TEKS = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


# ── 4.1: build menunggu CI di commit yang sama ──────────────────────────────


def test_ci_bisa_dipanggil_workflow_lain():
    assert "workflow_call" in _pemicu(CI)


def test_ci_tetap_jalan_untuk_pr_dan_push_main():
    """Kontrol negatif: `workflow_call` ditambahkan, pemicu lama tidak diganti."""
    pemicu = _pemicu(CI)
    assert set(pemicu["pull_request"]["branches"]) == {"staging", "main"}
    assert pemicu["push"]["branches"] == ["main"]


def test_job_ci_masih_bernama_lint_and_test():
    """Nama check PR yang mungkin diwajibkan branch protection tidak boleh berubah."""
    assert list(CI["jobs"]) == ["lint-and-test"]


def test_rilis_memanggil_ci_dari_commit_yang_sama():
    ci = DEPLOY["jobs"]["ci"]
    assert ci["uses"] == "./.github/workflows/ci.yml"
    assert ci["permissions"] == {"contents": "read"}


def test_build_pabrik_menunggu_ci():
    assert "ci" in _needs(DEPLOY["jobs"]["build-and-push"])


def test_build_demo_menunggu_ci_yang_sama():
    demo = DEPLOY["jobs"]["demo"]
    assert demo["uses"] == "./.github/workflows/demo-image.yml"
    assert _needs(demo) == ["ci"]
    assert demo["with"] == {"version": "${{ github.ref_name }}"}


def test_build_demo_tidak_menunggu_build_pabrik():
    """Build demo yang gagal tidak boleh menahan image yang ditarik pabrik, dan
    sebaliknya build pabrik tidak menunggu demo."""
    assert "demo" not in _needs(DEPLOY["jobs"]["build-and-push"])
    assert "build-and-push" not in _needs(DEPLOY["jobs"]["demo"])


def test_job_pemanggil_memberi_izin_yang_dibutuhkan_job_demo():
    """Izin job di workflow yang dipanggil cuma boleh sama atau lebih sempit dari izin
    job pemanggil; tanpa `packages: write` di sini build demo mati saat mulai."""
    diminta = DEMO["jobs"]["build-and-push"]["permissions"]
    diberi = DEPLOY["jobs"]["demo"]["permissions"]
    for izin, tingkat in diminta.items():
        assert diberi.get(izin) == tingkat, izin


def test_ci_tidak_memakai_secret_jadi_tidak_perlu_secrets_inherit():
    """Komentar boleh menyebutnya (dan memang menyebut, untuk memperingatkan)."""
    kode = [b for b in CI_TEKS.splitlines() if not b.strip().startswith("#")]
    assert not [b for b in kode if "secrets." in b]
    assert "secrets" not in DEPLOY["jobs"]["ci"]


def test_demo_tidak_lagi_jalan_sendiri_saat_tag():
    """Dengan `push: tags` sendiri, tiap tag membangun demo dua kali: sebelum CI dan
    sesudahnya."""
    assert "push" not in _pemicu(DEMO)


def test_dispatch_manual_demo_cuma_untuk_versi_yang_benar_benar_dirilis():
    langkah = DEMO["jobs"]["build-and-push"]["steps"]
    nama = [s.get("name") for s in langkah]
    syarat = langkah[nama.index("Require a published factory release")]
    assert syarat["if"] == "github.event_name == 'workflow_dispatch'"
    assert 'RELEASE="$REGISTRY/$IMAGE_NAME:$VERSION"' in syarat["run"]
    assert 'docker buildx imagetools inspect "$RELEASE"' in syarat["run"]
    assert nama.index("Log in to Container Registry") < nama.index("Require a published factory release")
    assert nama.index("Require a published factory release") < nama.index("Build and push demo image")
