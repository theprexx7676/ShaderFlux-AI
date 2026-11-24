"""Tests for re-checking generated output."""

from __future__ import annotations

import pytest

from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    Target,
    ToolInfo,
)
from shaderflux.pipeline.translate import TranslateOptions, translate
from shaderflux.tools.base import BackendRegistry, CrossOptions, ToolResult
from shaderflux.verify.recompile import recheck_generated

pytestmark = pytest.mark.unit


def tool_result(ok: bool, *, output: bytes | None = None, message: str | None = None) -> ToolResult:
    diagnostics = (
        (Diagnostic(severity=Severity.ERROR, message=message, tool="t"),) if message else ()
    )
    return ToolResult(
        ok=ok, output=output, diagnostics=diagnostics, tool=ToolInfo(name="fake", version="1"),
        command=("fake",), duration_s=0.0,
    )  # fmt: skip


class GlslCompiler:
    name = "fake-glsl"
    version = "1"
    languages = frozenset({ShaderLanguage.GLSL})

    def __init__(self, *, accept_generated: bool) -> None:
        self.accept_generated = accept_generated
        self.seen: list[str] = []

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult:
        self.seen.append(source.text)
        if "generated" in source.text and not self.accept_generated:
            return tool_result(False, message="'x' : bad layout")
        return tool_result(True, output=b"\x03\x02\x23\x07")


class Cross:
    name = "fake-cross"
    version = "1"
    targets = frozenset({ShaderLanguage.GLSL})

    def convert(
        self, spirv: bytes, target: Target, options: CrossOptions | None = None
    ) -> ToolResult:
        return tool_result(True, output=b"// generated glsl\n")


def registry(compiler: GlslCompiler | None) -> BackendRegistry:
    reg = BackendRegistry()
    if compiler is not None:
        reg.register_compiler(compiler)
    reg.register_cross_compiler(Cross())
    return reg


def glsl_source(stage: ShaderStage | None = ShaderStage.FRAGMENT) -> ShaderSource:
    return ShaderSource(text="void main() {}", language=ShaderLanguage.GLSL, stage=stage)


GLSL_TARGET = Target(language=ShaderLanguage.GLSL, version="450")
ROUNDTRIP = TranslateOptions(roundtrip=True)


def test_generated_glsl_is_compiled_again() -> None:
    compiler = GlslCompiler(accept_generated=True)
    result = translate(glsl_source(), GLSL_TARGET, registry=registry(compiler), options=ROUNDTRIP)
    assert result.ok
    assert result.stages[-1].name == "recompile generated glsl"
    assert compiler.seen == ["void main() {}", "// generated glsl\n"]


def test_a_failing_recheck_fails_the_translation_with_a_hint() -> None:
    result = translate(
        glsl_source(),
        GLSL_TARGET,
        registry=registry(GlslCompiler(accept_generated=False)),
        options=ROUNDTRIP,
    )
    assert not result.ok
    assert result.output_text == "// generated glsl\n"  # kept so the user can inspect it
    last = result.stages[-1]
    assert last.name == "recompile generated glsl"
    messages = [d.message for d in last.diagnostics]
    assert "'x' : bad layout" in messages
    assert any("--vulkan" in m for m in messages)


def test_recheck_can_be_turned_off() -> None:
    compiler = GlslCompiler(accept_generated=False)
    options = TranslateOptions(roundtrip=True, recheck=False)
    result = translate(glsl_source(), GLSL_TARGET, registry=registry(compiler), options=options)
    assert result.ok
    assert compiler.seen == ["void main() {}"]
    assert all("recompile" not in s.name for s in result.stages)


def test_unknown_stage_is_skipped_with_a_warning() -> None:
    stage = recheck_generated(
        "x", glsl_source(stage=None), GLSL_TARGET, registry(None), environment="vulkan1.2"
    )
    assert stage is not None
    assert stage.ok
    assert "stage is unknown" in stage.diagnostics[0].message


def test_missing_compiler_is_skipped_with_a_warning() -> None:
    stage = recheck_generated(
        "x", glsl_source(), GLSL_TARGET, registry(None), environment="vulkan1.2"
    )
    assert stage is not None
    assert stage.ok
    assert stage.diagnostics[0].severity is Severity.WARNING
    assert "was not recompiled" in stage.diagnostics[0].message


def test_hlsl_hint_names_dxc() -> None:
    stage = recheck_generated(
        "x",
        glsl_source(),
        Target(language=ShaderLanguage.HLSL),
        registry(None),
        environment="vulkan1.2",
    )
    assert stage is not None
    assert "dxc" in stage.diagnostics[0].message


@pytest.mark.parametrize("language", [ShaderLanguage.SPIRV, ShaderLanguage.MSL])
def test_languages_without_a_checker_return_nothing(language: ShaderLanguage) -> None:
    assert (
        recheck_generated(
            "x", glsl_source(), Target(language=language), registry(None), environment="vulkan1.2"
        )
        is None
    )
