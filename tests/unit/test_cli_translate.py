"""CLI tests that need no external tools."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.cli.app import app
from shaderflux.cli.errors import EXIT_TOOL, EXIT_USAGE, exit_code_for
from shaderflux.cli.translate_cmd import parse_define
from shaderflux.core.errors import (
    InvalidInputError,
    LlmError,
    ToolFailedError,
    ToolMissingError,
    ToolTimeoutError,
    UnsupportedRouteError,
)

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_parse_define() -> None:
    assert parse_define("A") == ("A", None)
    assert parse_define("A=1") == ("A", "1")
    assert parse_define("A=") == ("A", "")
    assert parse_define("A=b=c") == ("A", "b=c")
    with pytest.raises(InvalidInputError):
        parse_define("=1")


def test_exit_codes_by_error_type() -> None:
    assert exit_code_for(InvalidInputError("x")) == EXIT_USAGE
    assert exit_code_for(UnsupportedRouteError("x")) == EXIT_USAGE
    assert exit_code_for(ToolMissingError("dxc")) == EXIT_USAGE
    assert exit_code_for(ToolFailedError("dxc", "crashed")) == EXIT_TOOL
    assert exit_code_for(ToolTimeoutError("dxc", 5)) == EXIT_TOOL
    assert exit_code_for(LlmError("x")) == EXIT_TOOL


def test_missing_file_is_a_usage_error() -> None:
    result = runner.invoke(app, ["translate", "does-not-exist.frag", "--to", "hlsl"])
    assert result.exit_code == EXIT_USAGE
    assert "no such file" in result.output
    assert "Traceback" not in result.output


def test_unknown_language_is_a_usage_error(tmp_path: Path) -> None:
    shader = tmp_path / "a.frag"
    shader.write_text("void main() {}")
    result = runner.invoke(app, ["translate", str(shader), "--to", "cobol"])
    assert result.exit_code == EXIT_USAGE
    assert "unknown language" in result.output


def test_same_language_is_refused_with_hint(tmp_path: Path) -> None:
    shader = tmp_path / "a.frag"
    shader.write_text("void main() {}")
    result = runner.invoke(app, ["translate", str(shader), "--to", "glsl"])
    assert result.exit_code == EXIT_USAGE
    assert "--roundtrip" in result.output


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_help_lists_every_option() -> None:
    result = runner.invoke(app, ["translate", "--help"])
    assert result.exit_code == 0
    # On CI the help text is coloured and the styling splits "--to" into pieces.
    text = ANSI.sub("", result.output)
    for flag in ("--to", "--from", "--stage", "--out", "--force", "--roundtrip", "--json"):
        assert flag in text
