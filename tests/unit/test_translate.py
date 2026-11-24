"""Orchestrator tests with fake backends (control flow, caching, errors)."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.errors import UnsupportedRouteError
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    Target,
    ToolInfo,
)
from shaderflux.pipeline.cache import TranslationCache
from shaderflux.pipeline.translate import TranslateOptions, translate
from shaderflux.tools.base import BackendRegistry, CrossOptions, ToolResult

pytestmark = pytest.mark.unit

SPIRV_BYTES = b"\x03\x02\x23\x07FAKE"


def tool_result(
    name: str, *, ok: bool = True, output: bytes | None = None, message: str | None = None
) -> ToolResult:
    diagnostics = (
        (Diagnostic(severity=Severity.ERROR, message=message, tool=name),) if message else ()
    )
    return ToolResult(
        ok=ok,
        output=output,
        diagnostics=diagnostics,
        tool=ToolInfo(name=name, version="1.0"),
        command=(name,),
        duration_s=0.0,
    )


class FakeCompiler:
    name = "fake-compiler"
    version = "1.0"

    def __init__(self, language: ShaderLanguage, *, fail: bool = False) -> None:
        self.languages = frozenset({language})
        self.fail = fail
        self.calls = 0

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult:
        self.calls += 1
        if self.fail:
            return tool_result(self.name, ok=False, message="boom")
        return tool_result(self.name, output=SPIRV_BYTES)


class FakeCross:
    name = "fake-cross"
    version = "1.0"
    targets = frozenset({ShaderLanguage.GLSL, ShaderLanguage.HLSL})

    def __init__(self) -> None:
        self.calls = 0
        self.last_options: CrossOptions | None = None

    def convert(
        self, spirv: bytes, target: Target, options: CrossOptions | None = None
    ) -> ToolResult:
        self.calls += 1
        self.last_options = options
        return tool_result(self.name, output=f"// {target.language.value} output\n".encode())


class FakeValidator:
    name = "fake-validator"
    version = "1.0"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def validate(self, spirv: bytes, *, environment: str | None = None) -> ToolResult:
        self.calls += 1
        if self.fail:
            return tool_result(self.name, ok=False, message="invalid module")
        return tool_result(self.name)


def make_registry(
    compiler: FakeCompiler | None = None,
    cross: FakeCross | None = None,
    validator: FakeValidator | None = None,
) -> BackendRegistry:
    registry = BackendRegistry()
    registry.register_compiler(compiler or FakeCompiler(ShaderLanguage.HLSL))
    registry.register_cross_compiler(cross or FakeCross())
    if validator is not None:
        registry.register_validator(validator)
    return registry


def hlsl_source(path: Path | None = None) -> ShaderSource:
    return ShaderSource(
        path=path,
        text="float4 main() : SV_Target { return 0; }",
        language=ShaderLanguage.HLSL,
        stage=ShaderStage.FRAGMENT,
    )


GLSL_TARGET = Target(language=ShaderLanguage.GLSL, version="450")


def test_full_route_collects_stages() -> None:
    result = translate(
        hlsl_source(), GLSL_TARGET, registry=make_registry(validator=FakeValidator())
    )
    assert result.ok
    assert result.output_text == "// glsl output\n"
    assert [s.name for s in result.stages] == [
        "compile hlsl",
        "validate spirv",
        "convert to glsl",
    ]
    assert result.run_id


def test_spirv_target_returns_bytes() -> None:
    result = translate(
        hlsl_source(),
        Target(language=ShaderLanguage.SPIRV),
        registry=make_registry(validator=FakeValidator()),
    )
    assert result.ok
    assert result.output_bytes == SPIRV_BYTES
    assert result.output_text is None


def test_stops_at_first_failure() -> None:
    cross = FakeCross()
    result = translate(
        hlsl_source(),
        GLSL_TARGET,
        registry=make_registry(compiler=FakeCompiler(ShaderLanguage.HLSL, fail=True), cross=cross),
    )
    assert not result.ok
    assert cross.calls == 0
    assert result.diagnostics[0].message == "boom"
    assert result.output_text is None


def test_validation_failure_blocks_conversion() -> None:
    cross = FakeCross()
    result = translate(
        hlsl_source(),
        GLSL_TARGET,
        registry=make_registry(cross=cross, validator=FakeValidator(fail=True)),
    )
    assert not result.ok
    assert cross.calls == 0
    assert result.stages[-1].name == "validate spirv"


def test_missing_validator_warns_but_continues() -> None:
    result = translate(hlsl_source(), GLSL_TARGET, registry=make_registry())
    assert result.ok
    validation = next(s for s in result.stages if s.name == "validate spirv")
    assert validation.diagnostics[0].severity is Severity.WARNING


def test_validation_can_be_disabled() -> None:
    validator = FakeValidator()
    result = translate(
        hlsl_source(),
        GLSL_TARGET,
        registry=make_registry(validator=validator),
        options=TranslateOptions(validate=False),
    )
    assert result.ok
    assert validator.calls == 0
    assert all(s.name != "validate spirv" for s in result.stages)


def test_missing_compiler_is_a_result_not_a_traceback() -> None:
    registry = BackendRegistry()
    registry.register_cross_compiler(FakeCross())
    result = translate(hlsl_source(), GLSL_TARGET, registry=registry)
    assert not result.ok
    assert result.stages[-1].name == "tools"
    assert "hlsl compiler" in result.diagnostics[0].message


def test_unsupported_route_raises() -> None:
    with pytest.raises(UnsupportedRouteError):
        translate(hlsl_source(), Target(language=ShaderLanguage.HLSL), registry=make_registry())


def test_cross_options_are_forwarded() -> None:
    cross = FakeCross()
    options = TranslateOptions(cross=CrossOptions(vulkan_semantics=True))
    translate(hlsl_source(), GLSL_TARGET, registry=make_registry(cross=cross), options=options)
    assert cross.last_options == CrossOptions(vulkan_semantics=True)


def test_cache_hit_skips_tools(tmp_path: Path) -> None:
    compiler, cross = FakeCompiler(ShaderLanguage.HLSL), FakeCross()
    registry = make_registry(compiler, cross)
    options = TranslateOptions(cache=TranslationCache(tmp_path / "cache"))
    first = translate(hlsl_source(), GLSL_TARGET, registry=registry, options=options)
    second = translate(hlsl_source(), GLSL_TARGET, registry=registry, options=options)
    assert not first.cached
    assert second.cached
    assert second.output_text == first.output_text
    assert (compiler.calls, cross.calls) == (1, 1)
    assert second.run_id != first.run_id


def test_cache_key_depends_on_target_and_source(tmp_path: Path) -> None:
    compiler = FakeCompiler(ShaderLanguage.HLSL)
    registry = make_registry(compiler)
    options = TranslateOptions(cache=TranslationCache(tmp_path / "cache"))
    translate(hlsl_source(), GLSL_TARGET, registry=registry, options=options)
    translate(hlsl_source(), Target(language=ShaderLanguage.HLSL, version="50"), registry=registry,
              options=TranslateOptions(cache=options.cache, roundtrip=True))  # fmt: skip
    changed = hlsl_source().model_copy(update={"text": "float4 main() : SV_Target { return 1; }"})
    translate(changed, GLSL_TARGET, registry=registry, options=options)
    assert compiler.calls == 3


def test_cache_is_invalidated_when_an_included_file_changes(tmp_path: Path) -> None:
    header = tmp_path / "common.hlsli"
    header.write_text("float a;\n")
    main = tmp_path / "main.hlsl"
    main.write_text('#include "common.hlsli"\nfloat4 main() : SV_Target { return a; }\n')
    source = hlsl_source(main).model_copy(update={"text": main.read_text()})
    compiler = FakeCompiler(ShaderLanguage.HLSL)
    registry = make_registry(compiler)
    options = TranslateOptions(cache=TranslationCache(tmp_path / "cache"))

    translate(source, GLSL_TARGET, registry=registry, options=options)
    translate(source, GLSL_TARGET, registry=registry, options=options)
    assert compiler.calls == 1
    header.write_text("float a = 2;\n")
    translate(source, GLSL_TARGET, registry=registry, options=options)
    assert compiler.calls == 2


def test_missing_include_fails_before_any_tool_runs(tmp_path: Path) -> None:
    main = tmp_path / "main.hlsl"
    main.write_text('#include "missing.hlsli"\n')
    compiler = FakeCompiler(ShaderLanguage.HLSL)
    result = translate(hlsl_source(main), GLSL_TARGET, registry=make_registry(compiler))
    assert not result.ok
    assert compiler.calls == 0
    assert result.stages[0].name == "includes"
    assert "missing.hlsli" in result.diagnostics[0].message
