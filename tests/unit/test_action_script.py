"""Tests for scripts/action-lint.sh, the logic behind the GitHub Action."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform == "win32", reason="the action script needs bash"),
    pytest.mark.skipif(shutil.which("bash") is None, reason="bash not found"),
]

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "action-lint.sh"


def run(tmp_path: Path, **inputs: str) -> subprocess.CompletedProcess[str]:
    bin_dir = Path(sys.executable).parent
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        **{f"INPUT_{key.upper()}": value for key, value in inputs.items()},
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
    )


@pytest.fixture
def shaders(tmp_path: Path, corpus: Path) -> Path:
    target = tmp_path / "shaders" / "deep"
    target.mkdir(parents=True)
    shutil.copy(corpus / "hlsl" / "collision.hlsl", target / "collision.hlsl")
    shutil.copy(corpus / "hlsl" / "clean_matrix.hlsl", tmp_path / "shaders" / "clean.hlsl")
    return tmp_path


def test_errors_fail_the_job_but_the_sarif_is_still_written(shaders: Path) -> None:
    result = run(shaders, paths="shaders/deep/collision.hlsl", sarif_file="out.sarif")
    assert result.returncode == 1
    sarif = json.loads((shaders / "out.sarif").read_text())
    assert {r["ruleId"] for r in sarif["runs"][0]["results"]} >= {"BND001"}
    assert "BND001" in result.stdout


def test_fail_on_never_always_passes(shaders: Path) -> None:
    result = run(shaders, paths="shaders/deep/collision.hlsl", fail_on="never")
    assert result.returncode == 0


def test_clean_shader_passes(shaders: Path) -> None:
    result = run(shaders, paths="shaders/clean.hlsl")
    assert result.returncode == 0
    assert "no problems" in result.stdout


def test_recursive_globs_and_several_patterns(shaders: Path) -> None:
    result = run(shaders, paths="shaders/**/*.hlsl", fail_on="never")
    assert result.returncode == 0
    assert "checking 2 file(s)" in result.stdout
    result = run(shaders, paths="shaders/clean.hlsl shaders/deep/*.hlsl", fail_on="never")
    assert "checking 2 file(s)" in result.stdout


def test_target_any_skips_the_binding_rules(shaders: Path) -> None:
    result = run(shaders, paths="shaders/deep/collision.hlsl", target="any")
    assert result.returncode == 0


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ({}, "'paths' input is required"),
        ({"paths": "nothing/*.hlsl"}, "no shader files matched"),
        ({"paths": "shaders/clean.hlsl", "fail_on": "explode"}, "fail-on must be"),
        ({"paths": "shaders/clean.hlsl", "target": "dx9"}, "target must be"),
    ],
)
def test_bad_inputs_are_usage_errors(shaders: Path, inputs: dict[str, str], message: str) -> None:
    result = run(shaders, **inputs)
    assert result.returncode == 2
    assert message in result.stderr


def test_shell_metacharacters_in_inputs_are_not_executed(shaders: Path) -> None:
    marker = shaders / "pwned"
    result = run(shaders, paths=f"shaders/clean.hlsl; touch {marker}", fail_on="never")
    assert not marker.exists()
    assert result.returncode != 0 or "touch" not in result.stdout
    result = run(shaders, paths="shaders/clean.hlsl", target=f"any; touch {marker}")
    assert result.returncode == 2
    assert not marker.exists()


def test_action_definition_passes_inputs_through_the_environment() -> None:
    import yaml

    action = yaml.safe_load((ROOT / "action.yml").read_text())
    steps = action["runs"]["steps"]
    lint = next(s for s in steps if s.get("name") == "Lint shaders")
    assert "${{" not in lint["run"], "inputs must reach the script only via env, not the command"
    assert set(lint["env"]) == {"INPUT_PATHS", "INPUT_FAIL_ON", "INPUT_TARGET", "INPUT_SARIF_FILE"}
    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["paths"]["required"] is True
