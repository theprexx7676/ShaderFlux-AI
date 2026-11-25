"""``translate --repair`` end to end: real tools, scripted model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.cli.app import app
from shaderflux.cli.errors import EXIT_TOOL
from shaderflux.core.errors import LlmError
from shaderflux.llm.provider import FakeProvider
from shaderflux.workflows import translate_file
from tests.conftest import require_tool

pytestmark = [pytest.mark.integration, pytest.mark.needs_tools]

runner = CliRunner()

FIX = json.dumps(
    {
        "summary": "use a literal",
        "edits": [
            {
                "file": "broken.frag",
                "start_line": 3,
                "end_line": 3,
                "expected": "void main() { color = vec4(undefined_thing); }",
                "replacement": "void main() { color = vec4(1.0); }",
                "reason": "undeclared",
            }
        ],
        "confidence": "high",
    }
)


@pytest.fixture(autouse=True)
def _tools() -> None:
    require_tool("spirv-cross", "spirv-val", "glslangValidator")


def use_provider(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> None:
    monkeypatch.setattr(translate_file, "AnthropicProvider", lambda **_: provider)


def test_repair_fixes_prints_the_diff_and_saves_the_fixed_source(
    corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, FakeProvider([FIX]))
    fixed = tmp_path / "fixed.frag"
    out = tmp_path / "out.hlsl"
    result = runner.invoke(
        app,
        [
            "translate", str(corpus / "glsl" / "broken.frag"), "--to", "hlsl", "--repair",
            "--write-fixed", str(fixed), "--out", str(out),
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "AI-assisted change" in result.output
    assert "+void main() { color = vec4(1.0); }" in result.output
    assert "vec4(1.0)" in fixed.read_text()
    assert "SPIRV_Cross_Output" in out.read_text()
    assert "undefined_thing" in (corpus / "glsl" / "broken.frag").read_text()


def test_repair_failure_keeps_the_error_exit_code(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, FakeProvider(["not json"] * 3))
    result = runner.invoke(
        app, ["translate", str(corpus / "glsl" / "broken.frag"), "--to", "hlsl", "--repair"]
    )
    assert result.exit_code == 1
    assert "gave up after 3" in result.output
    assert "translation failed" in result.output


def test_model_failure_exits_with_the_tool_failure_code(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_provider(monkeypatch, FakeProvider([LlmError("rate limited by the API")]))
    result = runner.invoke(
        app, ["translate", str(corpus / "glsl" / "broken.frag"), "--to", "hlsl", "--repair"]
    )
    assert result.exit_code == EXIT_TOOL
    assert "rate limited" in result.output


def test_dry_run_sends_nothing_and_shows_the_prompt(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider([FIX])
    use_provider(monkeypatch, provider)
    result = runner.invoke(
        app,
        [
            "translate",
            str(corpus / "glsl" / "broken.frag"),
            "--to",
            "hlsl",
            "--repair",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "Nothing was sent" in result.output
    assert "undefined_thing" in result.output
    assert "system@1+repair_compile_error@1" in result.output
    assert provider.requests == []


def test_repair_is_not_attempted_when_the_shader_already_compiles(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider([FIX])
    use_provider(monkeypatch, provider)
    result = runner.invoke(
        app, ["translate", str(corpus / "glsl" / "textured.frag"), "--to", "hlsl", "--repair"]
    )
    assert result.exit_code == 0
    assert "AI-assisted" not in result.output
    assert provider.requests == []
