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


def test_publishes_only_the_cpu_suffixed_tag():
    tags = _lines(_build_step()["with"]["tags"])
    assert tags == ["${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ env.VERSION }}-cpu"]


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


def test_runs_on_every_release_tag_and_on_demand_for_an_older_one():
    triggers = _workflow()[True]  # YAML 1.1 reads the `on:` key as True
    assert triggers["push"]["tags"] == ["v*.*.*"]
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
