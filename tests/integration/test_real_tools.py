"""Integration tests that run the real external tools.

Skipped automatically when a tool is not installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shaderflux.core.models import ShaderLanguage, ShaderSource, ShaderStage, Target
from shaderflux.tools.glsl import GlslangBackend, GlslcBackend
from shaderflux.tools.spirv_cross import CrossOptions, SpirvCrossBackend
from shaderflux.tools.spirv_tools import SpirvToolsBackend, looks_like_spirv
from tests.conftest import require_any, require_tool

pytestmark = [pytest.mark.integration, pytest.mark.needs_tools]

VULKAN = Target(language=ShaderLanguage.SPIRV, environment="vulkan1.2")


def glsl_source(corpus: Path, name: str, stage: ShaderStage, **defines: str) -> ShaderSource:
    path = corpus / "glsl" / name
    return ShaderSource(
        path=path,
        text=path.read_text(),
        language=ShaderLanguage.GLSL,
        stage=stage,
        defines=dict(defines),
    )


@pytest.fixture(params=["glslangValidator", "glslc"])
def glsl_backend(request: pytest.FixtureRequest) -> GlslangBackend | GlslcBackend:
    require_tool(request.param)
    if request.param == "glslc":
        return GlslcBackend.discover()
    return GlslangBackend.discover()


def test_glsl_compiles_to_valid_spirv(
    glsl_backend: GlslangBackend | GlslcBackend, corpus: Path
) -> None:
    require_tool("spirv-val")
    result = glsl_backend.compile(
        glsl_source(corpus, "textured.frag", ShaderStage.FRAGMENT), target=VULKAN
    )
    assert result.ok, result.diagnostics
    assert result.output is not None
    assert looks_like_spirv(result.output)
    assert result.tool.version
    validation = SpirvToolsBackend.discover().validate(result.output, environment="vulkan1.2")
    assert validation.ok, validation.diagnostics


def test_vertex_stage(glsl_backend: GlslangBackend | GlslcBackend, corpus: Path) -> None:
    result = glsl_backend.compile(
        glsl_source(corpus, "passthrough.vert", ShaderStage.VERTEX), target=VULKAN
    )
    assert result.ok, result.diagnostics


def test_glsl_error_has_located_diagnostic(
    glsl_backend: GlslangBackend | GlslcBackend, corpus: Path
) -> None:
    result = glsl_backend.compile(
        glsl_source(corpus, "broken.frag", ShaderStage.FRAGMENT), target=VULKAN
    )
    assert not result.ok
    assert result.output is None
    located = [d for d in result.errors if d.line is not None]
    assert located
    assert located[0].file == "broken.frag"
    assert located[0].line == 3
    assert "undefined_thing" in located[0].message


def test_defines_are_passed(glsl_backend: GlslangBackend | GlslcBackend, corpus: Path) -> None:
    without = glsl_backend.compile(
        glsl_source(corpus, "defines.frag", ShaderStage.FRAGMENT), target=VULKAN
    )
    assert not without.ok
    with_define = glsl_backend.compile(
        glsl_source(corpus, "defines.frag", ShaderStage.FRAGMENT, TINT="0.5"), target=VULKAN
    )
    assert with_define.ok, with_define.diagnostics


def test_command_is_recorded(glsl_backend: GlslangBackend | GlslcBackend, corpus: Path) -> None:
    result = glsl_backend.compile(
        glsl_source(corpus, "passthrough.vert", ShaderStage.VERTEX), target=VULKAN
    )
    assert result.command
    assert result.command[0].endswith(("glslangValidator", "glslc"))


def compile_textured(corpus: Path) -> bytes:
    require_any("glslangValidator", "glslc")
    backend = (
        GlslangBackend.discover()
        if GlslangBackend is not None and __import__("shutil").which("glslangValidator")
        else GlslcBackend.discover()
    )
    result = backend.compile(
        glsl_source(corpus, "textured.frag", ShaderStage.FRAGMENT), target=VULKAN
    )
    assert result.ok
    assert result.output is not None
    return result.output


def test_spirv_cross_to_glsl_hlsl_and_reflection(corpus: Path) -> None:
    require_tool("spirv-cross")
    spirv = compile_textured(corpus)
    cross = SpirvCrossBackend.discover()

    glsl = cross.convert(
        spirv,
        Target(language=ShaderLanguage.GLSL, version="450"),
        CrossOptions(vulkan_semantics=True),
    )
    assert glsl.ok, glsl.diagnostics
    assert "#version 450" in glsl.text
    assert "void main()" in glsl.text

    hlsl = cross.convert(spirv, Target(language=ShaderLanguage.HLSL, version="50"))
    assert hlsl.ok, hlsl.diagnostics
    assert "cbuffer Params" in hlsl.text
    assert "register(" in hlsl.text

    reflection = cross.reflect(spirv)
    assert reflection.ok
    data = json.loads(reflection.text)
    assert data["entryPoints"][0]["mode"] == "frag"
    assert data["inputs"][0]["location"] == 0


def test_spirv_cross_reports_garbage_input() -> None:
    require_tool("spirv-cross")
    result = SpirvCrossBackend.discover().convert(
        b"\x03\x02\x23\x07\x00", Target(language=ShaderLanguage.GLSL)
    )
    assert not result.ok
    assert result.errors


def test_converted_glsl_recompiles(corpus: Path) -> None:
    """Round trip: GLSL -> SPIR-V -> GLSL -> SPIR-V must still compile."""
    require_tool("spirv-cross", "glslangValidator")
    spirv = compile_textured(corpus)
    glsl = SpirvCrossBackend.discover().convert(
        spirv,
        Target(language=ShaderLanguage.GLSL, version="450"),
        CrossOptions(vulkan_semantics=True),
    )
    assert glsl.ok
    again = GlslangBackend.discover().compile(
        ShaderSource(text=glsl.text, language=ShaderLanguage.GLSL, stage=ShaderStage.FRAGMENT),
        target=VULKAN,
    )
    assert again.ok, again.diagnostics


def test_validator_flags_corrupt_module(corpus: Path) -> None:
    require_tool("spirv-val")
    spirv = bytearray(compile_textured(corpus))
    spirv[12:16] = (1).to_bytes(4, "little")  # id bound too small
    result = SpirvToolsBackend.discover().validate(bytes(spirv))
    assert not result.ok
    assert any("ID bound" in d.message for d in result.errors)


def test_disassemble_and_optimize(corpus: Path) -> None:
    require_tool("spirv-dis", "spirv-opt")
    spirv = compile_textured(corpus)
    tools = SpirvToolsBackend.discover()
    dis = tools.disassemble(spirv)
    assert dis.ok
    assert "OpEntryPoint Fragment" in dis.text
    opt = tools.optimize(spirv)
    assert opt.ok
    assert opt.output is not None
    assert looks_like_spirv(opt.output)


def test_compute_stage(glsl_backend: GlslangBackend | GlslcBackend, corpus: Path) -> None:
    result = glsl_backend.compile(
        glsl_source(corpus, "compute.comp", ShaderStage.COMPUTE), target=VULKAN
    )
    assert result.ok, result.diagnostics
    assert result.output is not None
    assert looks_like_spirv(result.output)


def test_reflect_helper_on_real_module(corpus: Path) -> None:
    from shaderflux.analysis.reflection import ResourceKind, reflect

    require_tool("spirv-cross")
    spirv = compile_textured(corpus)
    reflection = reflect(spirv, SpirvCrossBackend.discover())
    params = reflection.find("Params")
    assert params is not None
    assert params.kind is ResourceKind.UNIFORM_BUFFER
    assert params.slot == (0, 0)
    assert reflection.find("tex") is not None


def test_file_named_like_an_option_still_compiles(tmp_path: Path, corpus: Path) -> None:
    """Regression: a file called -V.frag used to be read by glslang as the -V option."""
    require_any("glslangValidator", "glslc")
    odd = tmp_path / "-V.frag"
    odd.write_text((corpus / "glsl" / "textured.frag").read_text())
    backend = (
        GlslangBackend.discover()
        if __import__("shutil").which("glslangValidator")
        else GlslcBackend.discover()
    )
    source = ShaderSource(
        path=odd, text=odd.read_text(), language=ShaderLanguage.GLSL, stage=ShaderStage.FRAGMENT
    )
    result = backend.compile(source, target=VULKAN)
    assert result.ok, result.diagnostics
