"""The CPU demo image workflow must never reach a factory PC.

Factory PCs update by reading the `latest` marker under `delta-anugrah/autograde`, so
the demo build may publish only `vX.Y.Z-cpu` and must keep its own build cache.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
DEMO = WORKFLOWS / "demo-image.yml"
RELEASE = WORKFLOWS / "deploy.yml"


def _text(path: Path = DEMO) -> str:
    return path.read_text(encoding="utf-8")


def _workflow(path: Path = DEMO) -> dict:
    return yaml.safe_load(_text(path))


def _build_step() -> dict:
    steps = _workflow()["jobs"]["build-and-push"]["steps"]
    return next(s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action"))


def _lines(block: str) -> list[str]:
    return [line.strip() for line in block.splitlines() if line.strip()]


def _build_args() -> dict:
    return dict(line.split("=", 1) for line in _lines(_build_step()["with"]["build-args"]))


def test_never_publishes_the_latest_marker():
    code = [line for line in _text().splitlines() if not line.strip().startswith("#")]
    assert not [line for line in code if re.search(r":latest\b", line)], "factory PCs update from :latest"


def test_builds_only_the_candidate_tag():
    """Batch 4.2: the build writes a candidate; `promote` writes `vX.Y.Z-cpu` after smoke."""
    tags = _lines(_build_step()["with"]["tags"])
    assert tags == ["${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:candidate-${{ env.VERSION }}-cpu"]


def test_promotes_only_the_cpu_suffixed_tag():
    promote = _workflow()["jobs"]["promote"]["steps"]
    run = next(s["run"] for s in promote if s.get("name") == "Promote candidate to the demo tag")
    assert '--tag "$REGISTRY/$IMAGE_NAME:$VERSION-cpu" "$SOURCE"' in run
    assert run.count("--tag") == 1


def test_builds_cpu_torch_without_the_camera_sdk():
    args = _build_args()
    assert args["TORCH_VARIANT"] == "cpu"
    assert args["WITH_SDK"] == "false"
    assert args["APP_VERSION"] == "${{ env.VERSION }}"


def test_keeps_its_own_build_cache():
    """Sharing `:buildcache` would overwrite the CUDA layers the factory release reuses."""
    build = _build_step()["with"]
    for key in ("cache-from", "cache-to"):
        assert ":buildcache-cpu" in build[key]
        assert not re.search(r":buildcache(,|$)", build[key])
        assert "type=gha" not in build[key]


def test_publishes_under_the_same_pinned_image_name_as_the_release():
    assert _workflow()["env"]["IMAGE_NAME"] == _workflow(RELEASE)["env"]["IMAGE_NAME"]


def test_runs_when_the_release_calls_it_and_on_demand_for_an_older_one():
    """Every release tag reaches this workflow through deploy.yml, after CI (batch 4.1)."""
    triggers = _workflow()[True]  # YAML 1.1 reads the `on:` key as True
    assert triggers["workflow_call"]["inputs"]["version"] == {
        "description": "Release tag being built, e.g. v1.20.0",
        "required": True,
        "type": "string",
    }
    assert triggers["workflow_dispatch"]["inputs"]["version"]["required"] is True


def test_builds_the_released_code_not_the_dispatching_branch():
    steps = _workflow()["jobs"]["build-and-push"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "refs/tags/${{ env.VERSION }}"


def test_refuses_versions_that_are_not_released_on_main():
    text = _text()
    assert "git merge-base --is-ancestor HEAD origin/main" in text
    assert r"^v[0-9]+\.[0-9]+\.[0-9]+$" in text


def test_refuses_to_overwrite_an_existing_demo_image():
    assert 'docker buildx imagetools inspect "$IMAGE"' in _text()


def test_dispatch_input_never_reaches_a_shell_script_directly():
    """`${{ inputs.* }}` inside `run:` is script injection; it may only feed `env`."""
    steps = _workflow()["jobs"]["build-and-push"]["steps"]
    for step in steps:
        assert "inputs." not in step.get("run", ""), step.get("name")


def test_the_factory_release_is_still_gpu_with_sdk():
    release = _text(RELEASE)
    assert "TORCH_VARIANT=cu126" in release
    assert "WITH_SDK=true" in release


# ── automatic demo upgrade (demo-deploy.yml, 2026-10-09) ─────────────────────

DEPLOY_DEMO = WORKFLOWS / "demo-deploy.yml"


def test_demo_upgrades_only_after_both_images_are_released():
    """A version whose factory image failed (build or smoke) never reaches the demo either:
    `deploy-demo` waits for the factory `promote` AND the demo image (final review 2026-10-09)."""
    job = _workflow(RELEASE)["jobs"]["deploy-demo"]
    assert set(job["needs"]) == {"promote", "demo"}
    assert job["uses"] == "./.github/workflows/demo-deploy.yml"
    assert job["with"]["version"] == "${{ github.ref_name }}"
    # v1.27.0 (2026-10-10): without `secrets: inherit` the called job ran in environment `demo`
    # and still read all four DEMO_SSH_* as empty (ssh printed its usage). A reusable workflow
    # only sees the secrets its caller hands over, environment secrets included.
    assert job["secrets"] == "inherit"
    # A manual demo-image run (an older version) does not deploy; Run workflow on demo-deploy does.
    assert "deploy-demo" not in _workflow()["jobs"]


def test_demo_deploy_runs_one_at_a_time_in_the_demo_environment():
    wf = _workflow(DEPLOY_DEMO)
    job = wf["jobs"]["deploy"]
    assert job["environment"] == "demo"
    assert wf["concurrency"] == {"group": "demo-deploy", "cancel-in-progress": False}
    assert set(wf[True]) == {"workflow_call", "workflow_dispatch"}  # YAML 1.1: `on:` is True
    assert wf["permissions"] == {"contents": "read"}


def test_demo_deploy_only_sends_upgrade_and_checks_the_host_key():
    text = _text(DEPLOY_DEMO)
    assert '"upgrade $VERSION"' in text
    assert r"^v[0-9]+\.[0-9]+\.[0-9]+$" in text
    assert not re.search(r":latest\b", text), "factory PCs update from :latest"
    assert "StrictHostKeyChecking=no" not in text
    assert "UserKnownHostsFile=" in text


def test_demo_deploy_input_never_reaches_a_shell_script_directly():
    """`${{ inputs.* }}` or `${{ secrets.* }}` inside `run:` is script injection: `env` only."""
    for step in _workflow(DEPLOY_DEMO)["jobs"]["deploy"]["steps"]:
        assert "${{" not in step.get("run", ""), step.get("name")
