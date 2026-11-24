"""Tests for the matrix-convention rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.analysis.findings import Confidence
from shaderflux.analysis.matrix_rules import check_matrices
from shaderflux.core.models import ShaderLanguage

pytestmark = pytest.mark.unit

HLSL = ShaderLanguage.HLSL
GLSL = ShaderLanguage.GLSL


def rules(text: str, language: ShaderLanguage = HLSL) -> list[str]:
    return [f.rule for f in check_matrices(text, language)]


def test_mixed_mul_conventions_are_flagged(corpus: Path) -> None:
    findings = check_matrices((corpus / "hlsl" / "mixed_mul.hlsl").read_text(), HLSL, file="m.hlsl")
    mixed = [f for f in findings if f.rule == "MAT001"]
    assert len(mixed) == 1
    assert mixed[0].line == 10  # the later, minority use
    assert mixed[0].suggestion


def test_consistent_mul_is_not_flagged(corpus: Path) -> None:
    text = (corpus / "hlsl" / "clean_matrix.hlsl").read_text()
    assert check_matrices(text, HLSL) == []


def test_matrix_matrix_mul_does_not_count_as_mixed() -> None:
    text = "float4x4 a; float4x4 b; float4 v;\nfloat4 f() { return mul(v, mul(a, b)); }"
    assert "MAT001" not in rules(text)


def test_non_matrix_arguments_are_ignored() -> None:
    assert rules("float3 a; float3 b;\nfloat f() { return mul(a, b); }") == []


def test_member_access_is_not_treated_as_a_matrix() -> None:
    text = "float4x4 m;\nfloat4 f(float4 v) { return mul(m[0], v) + mul(v, m); }"
    assert "MAT001" not in rules(text)  # m[0] is a row, a vector


def test_constant_buffer_matrix_without_layout(corpus: Path) -> None:
    findings = check_matrices((corpus / "hlsl" / "mixed_mul.hlsl").read_text(), HLSL)
    mat2 = [f for f in findings if f.rule == "MAT002"]
    assert [f.line for f in mat2] == [3]
    assert "viewProj" in mat2[0].message
    assert mat2[0].confidence is Confidence.MEDIUM


def test_explicit_layout_or_pragma_silences_mat002() -> None:
    explicit = "cbuffer C { row_major float4x4 m; };"
    pragma = "#pragma pack_matrix(row_major)\ncbuffer C { float4x4 m; };"
    assert "MAT002" not in rules(explicit)
    assert "MAT002" not in rules(pragma)


def test_matrix_outside_a_buffer_is_not_flagged() -> None:
    assert "MAT002" not in rules("float4 f() { float4x4 local = 0; return local[0]; }")


def test_constant_buffer_template_struct_is_checked() -> None:
    text = "struct Params { float4x4 mvp; };\nConstantBuffer<Params> cb : register(b0);"
    assert "MAT002" in rules(text)


def test_transpose_of_buffer_matrix(corpus: Path) -> None:
    findings = check_matrices((corpus / "hlsl" / "mixed_mul.hlsl").read_text(), HLSL)
    (mat3,) = [f for f in findings if f.rule == "MAT003"]
    assert mat3.line == 11
    assert mat3.confidence is Confidence.LOW


def test_commented_code_is_ignored() -> None:
    text = "// cbuffer C { float4x4 m; };\n/* mul(v, m); mul(m, v); */\n"
    assert rules(text) == []


def test_non_square_matrices_hlsl_and_glsl() -> None:
    assert rules("float2x3 m;") == ["MAT004"]
    assert rules("float3x3 m; float4x4 n;") == []
    assert rules("uniform mat2x3 m;", GLSL) == ["MAT004"]
    assert rules("uniform mat4 m;", GLSL) == []


def test_glsl_row_major_note() -> None:
    text = "layout(std140) uniform U { layout(row_major) mat4 m; } u;"
    assert rules(text, GLSL) == ["MAT005"]


def test_spirv_and_msl_are_not_analysed() -> None:
    assert check_matrices("anything", ShaderLanguage.SPIRV) == []
