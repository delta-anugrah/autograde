"""Tiga workflow rilis dirangkai sebagai satu alur: pemanggil dan yang dipanggil harus cocok.

`deploy.yml` memanggil `ci.yml` dan `demo-image.yml` (batch 4.1). GitHub baru memeriksa
kecocokan input, izin, dan urutan job saat tag didorong, jadi salah satu sisi yang
disunting tanpa sisi lain baru ketahuan di hari rilis. Ini membaca ketiganya bersama.
"""
from __future__ import annotations

from pathlib import Path

import yaml

AKAR = Path(__file__).resolve().parents[2]
RILIS = ".github/workflows/deploy.yml"
LANGKAH_BUILD_IMAGE = "docker/build-push-action"


def _muat(jalur: str) -> dict:
    return yaml.safe_load((AKAR / jalur).read_text(encoding="utf-8"))


def _pemicu(doc: dict) -> dict:
    return doc.get("on") or doc.get(True) or {}


def _needs(job: dict) -> set[str]:
    needs = job.get("needs") or []
    return {needs} if isinstance(needs, str) else set(needs)


def _job_panggilan(doc: dict) -> dict[str, dict]:
    return {nama: job for nama, job in doc["jobs"].items() if "uses" in job}


def _dipanggil(job: dict) -> dict:
    return _muat(job["uses"].removeprefix("./"))


def _membangun_image(job: dict) -> bool:
    if "uses" in job:
        return any(_membangun_image(j) for j in _dipanggil(job)["jobs"].values())
    return any(str(s.get("uses", "")).startswith(LANGKAH_BUILD_IMAGE) for s in job.get("steps", []))


def _leluhur(jobs: dict, nama: str) -> set[str]:
    hasil: set[str] = set()
    antre = list(_needs(jobs[nama]))
    while antre:
        n = antre.pop()
        if n not in hasil:
            hasil.add(n)
            antre.extend(_needs(jobs[n]))
    return hasil


def test_tiap_workflow_yang_dipanggil_ada_dan_bisa_dipanggil():
    panggilan = _job_panggilan(_muat(RILIS))
    assert set(panggilan) == {"ci", "demo"}
    for nama, job in panggilan.items():
        assert job["uses"].startswith("./.github/workflows/"), nama
        assert "workflow_call" in _pemicu(_dipanggil(job)), nama


def test_input_pemanggil_cocok_dengan_yang_diminta():
    panggilan = _job_panggilan(_muat(RILIS))
    assert panggilan, "tidak ada job pemanggil: test ini tidak memeriksa apa pun"
    for nama, job in panggilan.items():
        diminta = _pemicu(_dipanggil(job))["workflow_call"] or {}
        masukan = diminta.get("inputs") or {}
        dikirim = set(job.get("with") or {})
        assert dikirim <= set(masukan), f"{nama}: input tak dikenal {dikirim - set(masukan)}"
        wajib = {k for k, v in masukan.items() if v.get("required")}
        assert wajib <= dikirim, f"{nama}: input wajib tidak dikirim {wajib - dikirim}"


def test_izin_job_yang_dipanggil_tidak_melebihi_pemberian_pemanggil():
    """GitHub menolak job bersarang yang meminta izin lebih luas dari pemanggilnya."""
    tingkat = {"none": 0, "read": 1, "write": 2}
    panggilan = _job_panggilan(_muat(RILIS))
    assert panggilan, "tidak ada job pemanggil: test ini tidak memeriksa apa pun"
    for nama, job in panggilan.items():
        diberi = job.get("permissions") or {}
        for anak, isi in _dipanggil(job)["jobs"].items():
            for izin, minta in (isi.get("permissions") or {}).items():
                assert tingkat[minta] <= tingkat[diberi.get(izin, "none")], f"{nama}/{anak}: {izin}"


def test_tiap_job_yang_membangun_image_menunggu_ci():
    """Berlaku juga untuk job image ketiga yang ditambahkan kelak."""
    jobs = _muat(RILIS)["jobs"]
    pembangun = {nama for nama, job in jobs.items() if _membangun_image(job)}
    assert pembangun == {"build-and-push", "demo"}
    for nama in pembangun:
        assert "ci" in _leluhur(jobs, nama), nama


def test_ci_yang_dipanggil_menguji_commit_tag_itu_sendiri():
    """Checkout tanpa `ref` = `github.sha` pemanggil = commit tag. `ref: main` di sini
    akan menguji commit lain dari yang dibangun."""
    ci = _dipanggil(_muat(RILIS)["jobs"]["ci"])
    for job in ci["jobs"].values():
        for langkah in job["steps"]:
            if str(langkah.get("uses", "")).startswith("actions/checkout"):
                assert "ref" not in (langkah.get("with") or {}), langkah


def test_demo_yang_dipanggil_membangun_tag_yang_sama():
    rilis = _muat(RILIS)
    demo = _dipanggil(rilis["jobs"]["demo"])
    assert rilis["jobs"]["demo"]["with"]["version"] == "${{ github.ref_name }}"
    assert demo["env"]["VERSION"] == "${{ inputs.version || github.ref_name }}"
    checkout = next(
        s for s in demo["jobs"]["build-and-push"]["steps"] if str(s.get("uses", "")).startswith("actions/checkout")
    )
    assert checkout["with"]["ref"] == "refs/tags/${{ env.VERSION }}"
