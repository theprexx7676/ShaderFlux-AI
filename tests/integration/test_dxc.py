"""Integration tests against a real ``dxc``. Skipped when it is not installed."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.models import ShaderLanguage, ShaderSource, ShaderStage, Target
from shaderflux.tools.dxc import BindingPolicy, DxcBackend
from shaderflux.tools.spirv_tools import SpirvToolsBackend, looks_like_spirv
from tests.conftest import require_tool

pytestmark = [pytest.mark.integration, pytest.mark.needs_tools]

SPIRV = Target(language=ShaderLanguage.SPIRV, environment="vulkan1.2")


def source(corpus: Path, name: str) -> ShaderSource:
    path = corpus / "hlsl" / name
    return ShaderSource(
        path=path, text=path.read_text(), language=ShaderLanguage.HLSL, stage=ShaderStage.FRAGMENT
    )


def test_hlsl_to_valid_spirv(corpus: Path) -> None:
    require_tool("dxc", "spirv-val")
    result = DxcBackend.discover().compile(source(corpus, "textured.hlsl"), target=SPIRV)
    assert result.ok, result.diagnostics
    assert result.output is not None
    assert looks_like_spirv(result.output)
    validation = SpirvToolsBackend.discover().validate(result.output, environment="vulkan1.2")
    assert validation.ok, validation.diagnostics


def test_compile_error_is_located(corpus: Path) -> None:
    require_tool("dxc")
    result = DxcBackend.discover().compile(source(corpus, "broken.hlsl"), target=SPIRV)
    assert not result.ok
    assert any(d.line == 3 and "undefined_thing" in d.message for d in result.errors)


def test_dxil_compiles(corpus: Path) -> None:
    require_tool("dxc")
    result = DxcBackend.discover().check_dxil(source(corpus, "textured.hlsl"))
    assert result.ok, result.diagnostics


def test_binding_shift_flags_are_accepted_by_real_dxc(corpus: Path) -> None:
    """VERIFY item: confirms the -fvk-*-shift syntax we generate."""
    require_tool("dxc")
    policy = BindingPolicy(shifts={"t": 100, "s": 200})
    result = DxcBackend.discover(binding_policy=policy).compile(
        source(corpus, "textured.hlsl"), target=SPIRV
    )
    assert result.ok, result.diagnostics


# ---- claims that `shaderflux lint` makes about DXC, checked against the real thing -------------


def _slots(spirv: bytes) -> dict[tuple[int, int], list[str]]:
    from shaderflux.analysis.reflection import reflect
    from shaderflux.tools.spirv_cross import SpirvCrossBackend

    reflection = reflect(spirv, SpirvCrossBackend.discover())
    return {slot: [r.name for r in found] for slot, found in reflection.by_slot().items()}


def test_default_mapping_collides_and_the_proposed_flags_fix_it(corpus: Path) -> None:
    """BND001: DXC ignores the register type, and the flags we print really separate them."""
    from shaderflux.analysis.bindings import parse_hlsl_bindings, propose_policy

    require_tool("dxc", "spirv-cross")
    shader = corpus / "hlsl" / "collision.hlsl"
    text = shader.read_text()
    source = ShaderSource(
        path=shader, text=text, language=ShaderLanguage.HLSL, stage=ShaderStage.FRAGMENT
    )

    default = DxcBackend.discover().compile(source, target=SPIRV)
    assert default.ok, default.diagnostics
    assert default.output is not None
    crowded = {slot: names for slot, names in _slots(default.output).items() if len(names) > 1}
    assert crowded, "expected DXC to put several resources on one binding by default"
    assert (0, 0) in crowded

    plan = propose_policy(parse_hlsl_bindings(text))
    assert plan.policy is not None
    fixed = DxcBackend.discover(binding_policy=plan.policy).compile(source, target=SPIRV)
    assert fixed.ok, fixed.diagnostics
    assert fixed.output is not None
    assert all(len(names) == 1 for names in _slots(fixed.output).values()), _slots(fixed.output)


def test_the_fix_command_output_compiles_to_distinct_slots_without_any_flags(
    corpus: Path,
) -> None:
    """`shaderflux fix` puts the proposed bindings in the source: DXC needs no -fvk flags then."""
    from shaderflux.analysis.autofix import apply_edits, plan_fixes

    require_tool("dxc", "spirv-cross")
    original = (corpus / "hlsl" / "collision.hlsl").read_text()
    fixed_text = apply_edits(original, plan_fixes(original).edits)
    fixed = ShaderSource(
        path=corpus / "hlsl" / "collision.hlsl",
        text=fixed_text,
        language=ShaderLanguage.HLSL,
        stage=ShaderStage.FRAGMENT,
    )
    result = DxcBackend.discover().compile(fixed, target=SPIRV)  # default policy: no shifts
    assert result.ok, result.diagnostics
    assert result.output is not None
    slots = _slots(result.output)
    assert all(len(names) == 1 for names in slots.values()), slots
    assert len(slots) == 5, slots  # b0 t0 t1 s0 u0


def test_hlsl_translates_to_glsl_with_every_real_tool(corpus: Path) -> None:
    from shaderflux.pipeline.translate import TranslateOptions, translate
    from shaderflux.source.inputs import load_source
    from shaderflux.tools.base import CrossOptions
    from shaderflux.tools.registry import default_registry

    require_tool("dxc", "spirv-cross", "spirv-val", "glslangValidator")
    result = translate(
        load_source(corpus / "hlsl" / "textured.hlsl", stage=ShaderStage.FRAGMENT),
        Target(language=ShaderLanguage.GLSL, version="450"),
        registry=default_registry(),
        options=TranslateOptions(cross=CrossOptions(vulkan_semantics=True)),
    )
    assert result.ok, [d.format() for d in result.diagnostics]
    assert "void main()" in (result.output_text or "")
    assert result.stages[0].name == "includes"
    assert any(s.name == "compile hlsl" and s.tool and s.tool.name == "dxc" for s in result.stages)


def test_dxc_is_found_and_its_version_is_parsed() -> None:
    from shaderflux.tools.discovery import ToolState, doctor

    require_tool("dxc")
    report = doctor(keys=["dxc"])
    (status,) = report.tools
    assert status.state is ToolState.OK, status
    assert status.version, "the version regex did not match `dxc --version`"


def test_matrix_packing_defaults_and_the_fix_we_suggest(tmp_path: Path) -> None:
    """MAT002: an unqualified matrix packs like column_major, and #pragma pack_matrix flips it.

    Observed with DXC 1.9: reflection marks the SPIR-V RowMajor decoration on HLSL
    column-major members (the qualifier flips between the languages), identical offsets.
    """
    from shaderflux.analysis.reflection import parse_reflection
    from shaderflux.tools.spirv_cross import SpirvCrossBackend

    require_tool("dxc", "spirv-cross")
    body = (
        "cbuffer U : register(b0) { float4x4 plain; row_major float4x4 rowm;"
        " column_major float4x4 colm; };\n"
        "float4 main(float4 p : POSITION) : SV_Position"
        " { return mul(p, plain) + mul(p, rowm) + mul(p, colm); }\n"
    )

    def members(text: str) -> dict[str, tuple[bool, int | None]]:
        source = ShaderSource(text=text, language=ShaderLanguage.HLSL, stage=ShaderStage.VERTEX)
        compiled = DxcBackend.discover().compile(source, target=SPIRV)
        assert compiled.ok, compiled.diagnostics
        assert compiled.output is not None
        reflected = SpirvCrossBackend.discover().reflect(compiled.output)
        block = parse_reflection(reflected.text).find("type.U") or parse_reflection(
            reflected.text
        ).find("U")
        assert block is not None
        return {m.name: (m.row_major, m.offset) for m in block.members}

    default = members(body)
    assert default["plain"][0] == default["colm"][0] != default["rowm"][0]
    pragma = members("#pragma pack_matrix(row_major)\n" + body)
    assert pragma["plain"][0] == pragma["rowm"][0] != pragma["colm"][0]
    assert [v[1] for v in default.values()] == [v[1] for v in pragma.values()] == [0, 64, 128]
