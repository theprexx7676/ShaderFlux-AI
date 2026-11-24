"""End-to-end translation with the real tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.models import ShaderLanguage, Target
from shaderflux.pipeline.inputs import load_source
from shaderflux.pipeline.translate import TranslateOptions, translate
from shaderflux.tools.base import CrossOptions
from shaderflux.tools.registry import default_registry
from tests.conftest import require_tool

pytestmark = [pytest.mark.integration, pytest.mark.needs_tools]


def need_glsl_chain() -> None:
    require_tool("spirv-cross", "spirv-val", "glslangValidator")


def test_glsl_to_hlsl(corpus: Path) -> None:
    need_glsl_chain()
    result = translate(
        load_source(corpus / "glsl" / "textured.frag"),
        Target(language=ShaderLanguage.HLSL, version="50"),
        registry=default_registry(),
    )
    assert result.ok, result.diagnostics
    assert "cbuffer Params" in (result.output_text or "")
    assert [s.name for s in result.stages] == [
        "includes",
        "compile glsl",
        "validate spirv",
        "convert to hlsl",
    ]
    tooled = [s for s in result.stages if s.name != "includes"]
    assert all(s.tool and s.tool.name for s in tooled)
    # spirv-cross builds without --version legitimately report no version
    assert all(s.tool.version for s in tooled if s.tool and s.tool.name != "spirv-cross")


def test_glsl_to_spirv_validates(corpus: Path) -> None:
    need_glsl_chain()
    result = translate(
        load_source(corpus / "glsl" / "passthrough.vert"),
        Target(language=ShaderLanguage.SPIRV),
        registry=default_registry(),
    )
    assert result.ok, result.diagnostics
    assert result.output_bytes is not None
    assert result.output_bytes[:4] in (b"\x03\x02\x23\x07", b"\x07\x23\x02\x03")


def test_glsl_roundtrip_recompiles(corpus: Path) -> None:
    need_glsl_chain()
    registry = default_registry()
    options = TranslateOptions(roundtrip=True, cross=CrossOptions(vulkan_semantics=True))
    first = translate(
        load_source(corpus / "glsl" / "textured.frag"),
        Target(language=ShaderLanguage.GLSL, version="450"),
        registry=registry,
        options=options,
    )
    assert first.ok, first.diagnostics
    assert first.output_text is not None
    again = translate(
        load_source(corpus / "glsl" / "textured.frag").model_copy(
            update={"text": first.output_text, "path": None}
        ),
        Target(language=ShaderLanguage.SPIRV),
        registry=registry,
    )
    assert again.ok, again.diagnostics


def test_compile_error_is_reported_with_location(corpus: Path) -> None:
    need_glsl_chain()
    result = translate(
        load_source(corpus / "glsl" / "broken.frag"),
        Target(language=ShaderLanguage.HLSL),
        registry=default_registry(),
    )
    assert not result.ok
    assert result.output_text is None
    located = [d for d in result.diagnostics if d.line == 3]
    assert located
    assert "undefined_thing" in located[0].message
    assert result.stages[-1].name == "compile glsl"


def test_include_resolution_with_real_compiler(tmp_path: Path) -> None:
    need_glsl_chain()
    (tmp_path / "common.glsl").write_text("vec4 tint() { return vec4(0.5); }\n")
    shader = tmp_path / "main.frag"
    shader.write_text(
        "#version 450\n#extension GL_GOOGLE_include_directive : require\n"
        '#include "common.glsl"\n'
        "layout(location = 0) out vec4 color;\nvoid main() { color = tint(); }\n"
    )
    result = translate(
        load_source(shader),
        Target(language=ShaderLanguage.GLSL, version="450"),
        registry=default_registry(),
        options=TranslateOptions(roundtrip=True, cross=CrossOptions(vulkan_semantics=True)),
    )
    assert result.ok, result.diagnostics
    assert next(s for s in result.stages if s.name == "includes").ok


def test_cache_with_real_tools(corpus: Path, tmp_path: Path) -> None:
    from shaderflux.pipeline.cache import TranslationCache

    need_glsl_chain()
    options = TranslateOptions(cache=TranslationCache(tmp_path / "cache"))
    args = (load_source(corpus / "glsl" / "textured.frag"), Target(language=ShaderLanguage.HLSL))
    first = translate(*args, registry=default_registry(), options=options)
    second = translate(*args, registry=default_registry(), options=options)
    assert first.ok
    assert second.cached
    assert second.output_text == first.output_text
