"""CLI end-to-end tests with the real tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.cli.app import app
from shaderflux.cli.errors import EXIT_FAILED, EXIT_USAGE
from tests.conftest import require_tool

pytestmark = [pytest.mark.integration, pytest.mark.needs_tools]

runner = CliRunner()


@pytest.fixture(autouse=True)
def _tools() -> None:
    require_tool("spirv-cross", "spirv-val", "glslangValidator")


def test_translate_prints_hlsl(corpus: Path) -> None:
    result = runner.invoke(
        app,
        ["translate", str(corpus / "glsl" / "textured.frag"), "--to", "hlsl", "--hlsl-model", "50"],
    )
    assert result.exit_code == 0, result.output
    assert "cbuffer Params" in result.stdout


def test_translate_writes_file_and_protects_existing(corpus: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.hlsl"
    args = ["translate", str(corpus / "glsl" / "textured.frag"), "--to", "hlsl", "--out", str(out)]
    assert runner.invoke(app, args).exit_code == 0
    assert "cbuffer" in out.read_text()
    again = runner.invoke(app, args)
    assert again.exit_code == EXIT_USAGE
    assert "--force" in again.output
    assert runner.invoke(app, [*args, "--force"]).exit_code == 0


def test_spirv_output_requires_out_and_writes_valid_module(corpus: Path, tmp_path: Path) -> None:
    shader = str(corpus / "glsl" / "passthrough.vert")
    refused = runner.invoke(app, ["translate", shader, "--to", "spirv"])
    assert refused.exit_code == EXIT_USAGE
    out = tmp_path / "m.spv"
    assert runner.invoke(app, ["translate", shader, "--to", "spirv", "-o", str(out)]).exit_code == 0
    assert out.read_bytes()[:4] in (b"\x03\x02\x23\x07", b"\x07\x23\x02\x03")


def test_compile_error_exit_code_and_message(corpus: Path) -> None:
    result = runner.invoke(app, ["translate", str(corpus / "glsl" / "broken.frag"), "--to", "hlsl"])
    assert result.exit_code == EXIT_FAILED
    assert "broken.frag:3: error" in result.output
    assert "undefined_thing" in result.output


def test_define_and_json_output(corpus: Path) -> None:
    shader = str(corpus / "glsl" / "defines.frag")
    failing = runner.invoke(app, ["translate", shader, "--to", "hlsl"])
    assert failing.exit_code == EXIT_FAILED
    ok = runner.invoke(app, ["translate", shader, "--to", "hlsl", "-D", "TINT=0.5", "--json"])
    assert ok.exit_code == 0, ok.output
    data = json.loads(ok.stdout)
    assert data["ok"] is True
    assert data["output_text"]
    assert data["run_id"]
