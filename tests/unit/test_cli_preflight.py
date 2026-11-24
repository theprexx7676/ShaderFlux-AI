"""Option checks that must happen before any work (or any LLM spend)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.cli import translate_cmd
from shaderflux.cli.app import app
from shaderflux.cli.errors import EXIT_USAGE
from shaderflux.llm.provider import FakeProvider

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture
def shader(tmp_path: Path) -> Path:
    path = tmp_path / "a.frag"
    path.write_text("#version 450\nvoid main() {}\n")
    return path


@pytest.mark.parametrize(
    "flag",
    [["--dry-run"], ["--write-fixed", "x.frag"], ["--allow-large-edits"], ["--max-attempts", "2"]],
)
def test_repair_only_flags_are_refused_without_repair(shader: Path, flag: list[str]) -> None:
    result = runner.invoke(app, ["translate", str(shader), "--to", "hlsl", *flag])
    assert result.exit_code == EXIT_USAGE
    assert "only make sense together with --repair" in result.output


@pytest.mark.parametrize("value", ["0", "11", "-1"])
def test_max_attempts_is_bounded(shader: Path, value: str) -> None:
    result = runner.invoke(
        app, ["translate", str(shader), "--to", "hlsl", "--repair", "--max-attempts", value]
    )
    assert result.exit_code == 2  # click's own usage error


def test_existing_output_is_refused_before_any_model_call(
    shader: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider([])
    monkeypatch.setattr(translate_cmd, "AnthropicProvider", lambda **_: provider)
    out = tmp_path / "out.hlsl"
    out.write_text("precious")
    for extra in (["--out", str(out)], ["--write-fixed", str(out)]):
        result = runner.invoke(app, ["translate", str(shader), "--to", "hlsl", "--repair", *extra])
        assert result.exit_code == EXIT_USAGE
        assert "already exists" in result.output
    assert provider.requests == []
    assert out.read_text() == "precious"


def test_directories_are_refused_as_output_paths(shader: Path, tmp_path: Path) -> None:
    for flag in ("--out", "--report"):
        result = runner.invoke(app, ["translate", str(shader), "--to", "hlsl", flag, str(tmp_path)])
        assert result.exit_code == EXIT_USAGE
        assert "is a directory" in result.output


def test_force_allows_overwriting(shader: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.hlsl"
    out.write_text("old")
    result = runner.invoke(
        app, ["translate", str(shader), "--to", "hlsl", "--out", str(out), "--force"]
    )
    assert result.exit_code != EXIT_USAGE or "already exists" not in result.output
