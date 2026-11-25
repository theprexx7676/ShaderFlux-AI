"""The AI support is an optional extra: a normal install must work without the SDK."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.analysis.lint import lint_text
from shaderflux.cli.app import app
from shaderflux.core.errors import InvalidInputError, LlmError
from shaderflux.core.models import ShaderLanguage
from shaderflux.llm.anthropic_provider import AnthropicProvider, sdk_available
from shaderflux.llm.provider import LlmRequest
from shaderflux.workflows.translate_file import TranslateRequest, check_request

pytestmark = pytest.mark.unit

runner = CliRunner()
REQUEST = LlmRequest(task="t", system="s", user="u", schema={"type": "object"})


@pytest.fixture
def no_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import anthropic`` fail, as it does when the ``ai`` extra is not installed."""
    monkeypatch.setitem(sys.modules, "anthropic", None)


def test_importing_the_package_never_loads_the_sdk() -> None:
    code = (
        "import sys, shaderflux.api, shaderflux.cli.app, shaderflux.workflows.translate_file\n"
        "sys.exit(1 if 'anthropic' in sys.modules else 0)"
    )
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert run.returncode == 0, "anthropic is imported at start-up, so it is not optional"


def test_sdk_detection_follows_the_install(no_sdk: None) -> None:
    assert sdk_available() is False


def test_the_provider_explains_how_to_install_the_extra(no_sdk: None) -> None:
    with pytest.raises(LlmError, match=r"shaderflux\[ai\]"):
        AnthropicProvider().complete(REQUEST)


def test_repair_is_refused_up_front_without_the_sdk(no_sdk: None, tmp_path: Path) -> None:
    request = TranslateRequest(
        input_file=tmp_path / "a.frag", target_language=ShaderLanguage.HLSL, repair=True
    )
    with pytest.raises(InvalidInputError, match=r"shaderflux\[ai\]"):
        check_request(request)


def test_dry_run_and_injected_providers_do_not_need_the_sdk(no_sdk: None, tmp_path: Path) -> None:
    base = {"input_file": tmp_path / "a.frag", "target_language": ShaderLanguage.HLSL}
    check_request(TranslateRequest(**base, repair=True, dry_run=True))  # type: ignore[arg-type]
    check_request(TranslateRequest(**base, repair=True), needs_sdk=False)  # type: ignore[arg-type]
    check_request(TranslateRequest(**base))  # type: ignore[arg-type]


def test_cli_repair_without_the_sdk_exits_two_and_writes_nothing(
    no_sdk: None, tmp_path: Path
) -> None:
    shader = tmp_path / "a.frag"
    shader.write_text("#version 450\nvoid main() {}\n")
    out = tmp_path / "out.hlsl"
    result = runner.invoke(
        app, ["translate", str(shader), "--to", "hlsl", "--repair", "-o", str(out)]
    )
    assert result.exit_code == 2
    assert "shaderflux[ai]" in result.output
    assert not out.exists()


def test_everything_that_needs_no_ai_works_without_the_sdk(no_sdk: None, tmp_path: Path) -> None:
    assert {f.rule for f in lint_text("uniform float g;\n", ShaderLanguage.GLSL)} == {"VKG002"}
    shader = tmp_path / "a.hlsl"
    shader.write_text(
        "cbuffer C : register(b0) { row_major float4x4 m; };\nTexture2D t : register(t0);\n"
    )
    assert runner.invoke(app, ["fix", "--check", str(shader)]).exit_code == 1
    assert runner.invoke(app, ["init", str(tmp_path / "p")]).exit_code == 0


# ---- the install hint must not point at a PyPI name nobody here controls ---------------------


def test_the_install_hint_points_at_the_github_repository_not_a_bare_pypi_name() -> None:
    from shaderflux.llm.anthropic_provider import install_hint

    hint = install_hint("0.1.0")
    assert "git+https://github.com/theprexx7676/ShaderFlux-AI.git@v0.1.0" in hint
    assert "shaderflux[ai]" in hint
    # `pip install 'shaderflux[ai]'` would fail today, and would install a stranger's package
    # if anyone registered that name on PyPI.
    assert "pip install 'shaderflux[ai]'" not in hint
    assert 'pip install "shaderflux[ai]"' not in hint


def test_a_development_build_gets_no_release_tag_in_the_hint() -> None:
    from shaderflux.llm.anthropic_provider import install_hint

    hint = install_hint("0.0.0+unknown")
    assert "ShaderFlux-AI.git`" in hint or 'ShaderFlux-AI.git"' in hint
    assert "@v0.0.0" not in hint


def test_the_hint_users_see_comes_from_the_same_function(no_sdk: None) -> None:
    from shaderflux import __version__
    from shaderflux.llm.anthropic_provider import install_hint

    with pytest.raises(LlmError) as info:
        AnthropicProvider().complete(REQUEST)
    assert str(info.value) == install_hint(__version__)
