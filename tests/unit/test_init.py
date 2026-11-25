"""``shaderflux init``: starter files must be valid, safe and never clobber existing work."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.cli.app import app
from shaderflux.core.config import load_settings
from shaderflux.core.errors import InvalidInputError
from shaderflux.workflows.init_project import WORKFLOW_PATH, InitRequest, run_init

pytestmark = pytest.mark.unit

runner = CliRunner()
REPO = Path(__file__).resolve().parents[2]


def test_the_starter_config_loads_with_the_real_loader(tmp_path: Path) -> None:
    run_init(InitRequest(tmp_path))
    loaded = load_settings(cwd=tmp_path, environ={}, user_file=tmp_path / "none.toml")
    assert loaded.settings.default_environment == "vulkan1.2"
    assert loaded.settings.include_dirs == [Path("shaders/common")]
    assert loaded.settings.llm.enabled is False  # the AI stays off


def test_the_starter_config_has_no_api_key_setting(tmp_path: Path) -> None:
    run_init(InitRequest(tmp_path))
    text = (tmp_path / "shaderflux.toml").read_text()
    assert "api_key" not in tomllib.loads(text)
    assert "sk-" not in text


def test_the_workflow_is_the_same_as_the_documented_example(tmp_path: Path) -> None:
    run_init(InitRequest(tmp_path, github=True))
    written = (tmp_path / WORKFLOW_PATH).read_text()
    example = (REPO / "examples" / "workflows" / "lint-shaders.yml").read_text()
    body = lambda text: [  # noqa: E731
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    assert body(written) == body(example)


def test_without_github_only_the_config_is_written(tmp_path: Path) -> None:
    outcome = run_init(InitRequest(tmp_path))
    assert outcome.written == [tmp_path / "shaderflux.toml"]
    assert not (tmp_path / ".github").exists()


def test_existing_files_are_not_overwritten_and_nothing_is_half_written(tmp_path: Path) -> None:
    (tmp_path / "shaderflux.toml").write_text("mine = true\n")
    with pytest.raises(InvalidInputError, match="already exists"):
        run_init(InitRequest(tmp_path, github=True))
    assert (tmp_path / "shaderflux.toml").read_text() == "mine = true\n"
    assert not (tmp_path / ".github").exists()  # the clash was found before writing anything
    run_init(InitRequest(tmp_path, force=True))
    assert "ShaderFlux-AI settings" in (tmp_path / "shaderflux.toml").read_text()


@pytest.mark.parametrize(
    "bad", ["../x", "/etc", "a b", "x\ny: z", 'sh"ell', "a/../b", "", "$(id)", "-rf"]
)
def test_unsafe_shader_directories_are_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(InvalidInputError, match="invalid shader directory"):
        run_init(InitRequest(tmp_path, shaders_dir=bad, github=True))
    assert list(tmp_path.iterdir()) == []


def test_a_custom_shader_directory_reaches_the_workflow(tmp_path: Path) -> None:
    run_init(InitRequest(tmp_path, shaders_dir="assets/shaders/", github=True))
    text = (tmp_path / WORKFLOW_PATH).read_text()
    assert 'paths: ["assets/shaders/**"]' in text
    assert "assets/shaders/**/*.hlsl" in text


def test_a_file_in_place_of_the_directory_is_an_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(InvalidInputError, match="not a directory"):
        run_init(InitRequest(blocker))


def test_cli_writes_files_and_exits_zero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--github"])
    assert result.exit_code == 0
    assert "wrote" in result.output
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 2  # already exists
