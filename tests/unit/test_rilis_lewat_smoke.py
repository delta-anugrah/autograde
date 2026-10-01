"""Batch 4.2: an image gets its release tag only after it passed the smoke test.

Before this, `deploy.yml` pushed `vX.Y.Z` and `latest` straight from the build, so an
image that could not boot was found by the factory PC. Now both release workflows build
a `candidate-*` tag, `image-smoke.yml` checks that exact digest on a fresh runner, and a
`promote` job copies the digest to the release tags. These tests pin that order.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
NAMA_IMAGE = "ghcr.io/delta-anugrah/autograde"
DIGEST = "@${{ needs.build-and-push.outputs.digest }}"


def _muat(nama: str) -> dict:
    return yaml.safe_load((WORKFLOWS / nama).read_text(encoding="utf-8"))


def _pemicu(doc: dict) -> dict:
    return doc.get("on") or doc.get(True) or {}


def _needs(job: dict) -> set[str]:
    needs = job.get("needs") or []
    return {needs} if isinstance(needs, str) else set(needs)


def _kode(teks: str) -> list[str]:
    return [b for b in teks.splitlines() if not b.strip().startswith("#")]


DEPLOY = _muat("deploy.yml")
DEMO = _muat("demo-image.yml")
SMOKE = _muat("image-smoke.yml")
SMOKE_TEKS = (WORKFLOWS / "image-smoke.yml").read_text(encoding="utf-8")
RILIS = {"deploy.yml": DEPLOY, "demo-image.yml": DEMO}


def _langkah_build(doc: dict) -> dict:
    return next(
        s for s in doc["jobs"]["build-and-push"]["steps"] if str(s.get("uses", "")).startswith("docker/build-push-action")
    )


# ── build: cuma kandidat ────────────────────────────────────────────────────


@pytest.mark.parametrize("nama", sorted(RILIS))
def test_build_cuma_menulis_tag_kandidat(nama):
    tags = [b.strip() for b in _langkah_build(RILIS[nama])["with"]["tags"].splitlines() if b.strip()]
    assert len(tags) == 1, tags
    assert ":candidate-" in tags[0], tags
    assert not tags[0].endswith(":latest"), tags


@pytest.mark.parametrize("nama", sorted(RILIS))
def test_build_menyerahkan_digest_yang_dibangun(nama):
    job = RILIS[nama]["jobs"]["build-and-push"]
    assert job["outputs"]["digest"] == "${{ steps.build.outputs.digest }}"
    assert _langkah_build(RILIS[nama])["id"] == "build"


# ── smoke: digest yang sama, versi yang benar ───────────────────────────────


@pytest.mark.parametrize("nama", sorted(RILIS))
def test_smoke_memeriksa_digest_hasil_build(nama):
    """Digest, bukan tag: tag kandidat bisa tertimpa run lain di antara build dan smoke."""
    smoke = RILIS[nama]["jobs"]["smoke"]
    assert smoke["uses"] == "./.github/workflows/image-smoke.yml"
    assert _needs(smoke) == {"build-and-push"}
    assert smoke["with"]["image"] == NAMA_IMAGE + DIGEST


def test_nama_image_tertulis_sama_dengan_env_image_name():
    """`env` tidak tersedia di `with:` job pemanggil, jadi nama ditulis langsung."""
    for doc in RILIS.values():
        assert f"ghcr.io/{doc['env']['IMAGE_NAME']}" == NAMA_IMAGE


def test_smoke_pabrik_mengharapkan_versi_tag():
    w = DEPLOY["jobs"]["smoke"]["with"]
    assert w["version"] == w["label"] == "${{ github.ref_name }}"
    assert "demo" not in w


def test_smoke_demo_mengharapkan_label_cpu_dan_kit_demo():
    w = DEMO["jobs"]["smoke"]["with"]
    assert w["version"] == "${{ inputs.version || github.ref_name }}"
    assert w["label"] == "${{ inputs.version || github.ref_name }}-cpu"
    assert w["demo"] is True


# ── promote: satu-satunya penulis tag rilis ─────────────────────────────────


@pytest.mark.parametrize("nama", sorted(RILIS))
def test_promote_menunggu_smoke_dan_build(nama):
    assert _needs(RILIS[nama]["jobs"]["promote"]) == {"build-and-push", "smoke"}


@pytest.mark.parametrize("nama", sorted(RILIS))
def test_promote_menyalin_digest_tanpa_build_ulang(nama):
    promote = RILIS[nama]["jobs"]["promote"]
    assert promote["env"]["SOURCE"] == NAMA_IMAGE + DIGEST
    langkah = promote["steps"]
    assert not [s for s in langkah if str(s.get("uses", "")).startswith("docker/build-push-action")]
    run = "\n".join(s.get("run", "") for s in langkah)
    assert "docker buildx imagetools create" in run
    assert '"$SOURCE"' in run


@pytest.mark.parametrize("nama", sorted(RILIS))
def test_promote_memeriksa_ulang_tag_rilis_sebelum_menulis(nama):
    nama_langkah = [s.get("name", "") for s in RILIS[nama]["jobs"]["promote"]["steps"]]
    cek = next(i for i, n in enumerate(nama_langkah) if n.startswith("Reject existing"))
    tulis = next(i for i, n in enumerate(nama_langkah) if n.startswith("Promote candidate"))
    assert cek < tulis


def test_latest_cuma_ditulis_promote_pabrik():
    """`latest` = penanda yang dibaca launcher pabrik. Ditulis di tempat lain = image yang
    belum lolos smoke bisa sampai ke pabrik."""
    for nama, doc in {**RILIS, "image-smoke.yml": SMOKE}.items():
        for job_nama, job in doc["jobs"].items():
            for s in job.get("steps", []):
                teks = "\n".join(_kode(str(s.get("run", ""))) + _kode(str((s.get("with") or {}).get("tags", ""))))
                if re.search(r":latest\b", teks):
                    assert (nama, job_nama) == ("deploy.yml", "promote"), (nama, job_nama, s.get("name"))


def test_tag_kandidat_tidak_bisa_dikira_versi_rilis():
    """Validasi tag rilis menolak apa pun selain vX.Y.Z, jadi `candidate-*` tidak pernah
    bisa memicu rilis sendiri."""
    assert r"^v[0-9]+\.[0-9]+\.[0-9]+$" in (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")


# ── image-smoke.yml: cuma membaca ───────────────────────────────────────────


def test_smoke_bisa_dipanggil_dan_dijalankan_manual():
    pemicu = _pemicu(SMOKE)
    panggil = set(pemicu["workflow_call"]["inputs"])
    manual = set(pemicu["workflow_dispatch"]["inputs"])
    assert panggil == manual == {"image", "version", "label", "demo"}


def test_smoke_tidak_pernah_menulis_ke_registry():
    """Mode uji coba (dispatch manual) aman dijalankan kapan saja: tanpa izin tulis dan
    tanpa perintah yang menulis tag."""
    assert SMOKE["jobs"]["smoke"]["permissions"] == {"contents": "read", "packages": "read"}
    kode = "\n".join(_kode(SMOKE_TEKS))
    for terlarang in ("imagetools create", "docker push", "docker tag", "build-push-action"):
        assert terlarang not in kode, terlarang


def test_input_smoke_tidak_masuk_skrip_langsung():
    """`${{ inputs.* }}` di dalam `run:` = script injection; cuma boleh lewat `env`."""
    for s in SMOKE["jobs"]["smoke"]["steps"]:
        assert "inputs." not in s.get("run", ""), s.get("name")


def test_smoke_menjalankan_ketiga_cek():
    langkah = {s.get("name"): s for s in SMOKE["jobs"]["smoke"]["steps"]}
    assert "scripts/smoke_image.py" in langkah["Smoke (label, imports, console boot)"]["run"]
    tracker = langkah["Tracker works offline"]
    assert "tests/e2e/test_image_tracker_deps.py" in tracker["run"]
    assert tracker["env"]["E2E_WAJIB"] == "1"
    kit = langkah["Demo kit boots, seeds and serves a login"]
    assert kit["if"] == "${{ inputs.demo }}"
    assert kit["env"]["E2E_WAJIB"] == "1"
    assert "tests/e2e/test_demo_kit_docker.py" in kit["run"]


def test_urutan_cek_smoke():
    nama = [s.get("name") for s in SMOKE["jobs"]["smoke"]["steps"]]
    assert nama.index("Pull image") < nama.index("Smoke (label, imports, console boot)")
    assert nama.index("Smoke (label, imports, console boot)") < nama.index("Tracker works offline")


def test_disk_runner_dibersihkan_untuk_image_pabrik_saja():
    langkah = next(s for s in SMOKE["jobs"]["smoke"]["steps"] if s.get("name") == "Reclaim runner disk")
    assert langkah["if"] == "${{ !inputs.demo }}"
