"""Tests for configuration loading and precedence."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.cli.app import app
from shaderflux.core.config import find_project_file, load_settings
from shaderflux.core.errors import InvalidInputError

pytestmark = pytest.mark.unit

NO_USER = Path("/nonexistent/shaderflux-user-config.toml")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_defaults(tmp_path: Path) -> None:
    loaded = load_settings(cwd=tmp_path, environ={}, user_file=NO_USER)
    assert loaded.settings.default_environment == "vulkan1.2"
    assert loaded.settings.llm.enabled is False
    assert loaded.files == []
    assert loaded.sources["default_environment"] == "default"


def test_precedence_cli_over_env_over_project_over_user(tmp_path: Path) -> None:
    user = write(tmp_path / "user.toml", 'default_environment = "vulkan1.0"\ntool_timeout_s = 10\n')
    write(
        tmp_path / "project" / "shaderflux.toml",
        'default_environment = "vulkan1.1"\n[llm]\nmodel = "from-project"\n',
    )
    loaded = load_settings(
        cwd=tmp_path / "project",
        environ={"SHADERFLUX_ENVIRONMENT": "vulkan1.3", "SHADERFLUX_MODEL": "from-env"},
        user_file=user,
        cli_overrides={"llm.model": "from-cli", "tool_timeout_s": None},
    )
    s = loaded.settings
    assert s.default_environment == "vulkan1.3"
    assert loaded.sources["default_environment"] == "environment"
    assert s.llm.model == "from-cli"
    assert loaded.sources["llm.model"] == "command line"
    assert s.tool_timeout_s == 10  # None override ignored; user value wins
    assert "user file" in loaded.sources["tool_timeout_s"]
    assert len(loaded.files) == 2


def test_project_file_found_in_parent_directory(tmp_path: Path) -> None:
    write(tmp_path / "shaderflux.toml", "tool_timeout_s = 5\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_project_file(nested) == tmp_path / "shaderflux.toml"
    assert load_settings(cwd=nested, environ={}, user_file=NO_USER).settings.tool_timeout_s == 5


def test_tools_table_and_include_dirs(tmp_path: Path) -> None:
    write(
        tmp_path / "shaderflux.toml",
        'include_dirs = ["shaders/common"]\n[tools]\ndxc = "/opt/dxc/bin/dxc"\n',
    )
    s = load_settings(cwd=tmp_path, environ={}, user_file=NO_USER).settings
    assert s.tools == {"dxc": "/opt/dxc/bin/dxc"}
    assert s.include_dirs == [Path("shaders/common")]


def test_env_boolean_parsing(tmp_path: Path) -> None:
    on = load_settings(cwd=tmp_path, environ={"SHADERFLUX_LLM": "true"}, user_file=NO_USER)
    assert on.settings.llm.enabled is True
    with pytest.raises(InvalidInputError, match="true or false"):
        load_settings(cwd=tmp_path, environ={"SHADERFLUX_LLM": "maybe"}, user_file=NO_USER)


@pytest.mark.parametrize(
    "toml",
    ['api_key = "sk-ant-secret"\n', '[llm]\napi_key = "x"\n', 'ANTHROPIC_API_KEY = "x"\n'],
)
def test_api_key_in_config_file_is_rejected(tmp_path: Path, toml: str) -> None:
    write(tmp_path / "shaderflux.toml", toml)
    with pytest.raises(InvalidInputError, match="ANTHROPIC_API_KEY"):
        load_settings(cwd=tmp_path, environ={}, user_file=NO_USER)


def test_unknown_key_and_bad_value_are_reported(tmp_path: Path) -> None:
    write(tmp_path / "shaderflux.toml", "colour = 1\n")
    with pytest.raises(InvalidInputError, match="colour"):
        load_settings(cwd=tmp_path, environ={}, user_file=NO_USER)
    write(tmp_path / "shaderflux.toml", "[llm]\nmax_attempts = 99\n")
    with pytest.raises(InvalidInputError, match="max_attempts"):
        load_settings(cwd=tmp_path, environ={}, user_file=NO_USER)


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    write(tmp_path / "shaderflux.toml", "this is = = not toml")
    with pytest.raises(InvalidInputError, match="invalid TOML"):
        load_settings(cwd=tmp_path, environ={}, user_file=NO_USER)


def test_config_show_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    result = CliRunner().invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0
    assert '"default_environment": "vulkan1.2"' in result.stdout
