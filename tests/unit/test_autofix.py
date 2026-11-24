"""Deterministic fixes: no AI involved, so they must be exactly predictable."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.analysis.autofix import FIXABLE_RULES, apply_edits, plan_fixes
from shaderflux.analysis.lint import lint_text
from shaderflux.core.models import ShaderLanguage

pytestmark = pytest.mark.unit

HLSL = ShaderLanguage.HLSL


def fix(text: str, **kwargs: object) -> str:
    return apply_edits(text, plan_fixes(text, **kwargs).edits)  # type: ignore[arg-type]


def rules_of(text: str) -> set[str]:
    return {f.rule for f in lint_text(text, HLSL)}


def test_collision_corpus_shader_is_fixed_to_the_bindings_the_flags_would_give(
    corpus: Path,
) -> None:
    text = (corpus / "hlsl" / "collision.hlsl").read_text()
    plan = plan_fixes(text, rules={"BND001"})
    assert [e.rule for e in plan.edits] == ["BND001"] * 4  # b0 keeps binding 0; t0 t1 s0 u0 move
    fixed = apply_edits(text, plan.edits)
    assert "[[vk::binding(1, 0)]] Texture2D albedo : register(t0);" in fixed
    assert "[[vk::binding(2, 0)]] Texture2D normals : register(t1);" in fixed
    assert "[[vk::binding(3, 0)]] SamplerState samp : register(s0);" in fixed
    assert "[[vk::binding(4, 0)]] RWStructuredBuffer<float> output : register(u0);" in fixed
    assert "cbuffer Params : register(b0)" in fixed  # already on its final binding: untouched
    assert "BND001" not in rules_of(fixed)


def test_fixes_are_pure_insertions(corpus: Path) -> None:
    text = (corpus / "hlsl" / "collision.hlsl").read_text()
    plan = plan_fixes(text)
    fixed = apply_edits(text, plan.edits)
    restored = fixed
    for edit in plan.edits:
        restored = restored.replace(edit.text, "", 1)
    assert restored == text, "applying the fixes changed something other than inserting text"
    assert len(fixed) == len(text) + sum(len(e.text) for e in plan.edits)


def test_all_fixable_findings_disappear_and_a_second_run_changes_nothing(corpus: Path) -> None:
    text = (corpus / "hlsl" / "collision.hlsl").read_text()
    fixed = fix(text)
    assert not rules_of(fixed) & set(FIXABLE_RULES)
    assert plan_fixes(fixed).edits == []
    assert fix(fixed) == fixed


def test_matrix_layout_is_made_explicit_as_column_major(corpus: Path) -> None:
    text = (corpus / "hlsl" / "mixed_mul.hlsl").read_text()
    plan = plan_fixes(text, rules={"MAT002"})
    (edit,) = plan.edits
    assert (edit.rule, edit.line, edit.text) == ("MAT002", 3, "column_major ")
    assert "    column_major float4x4 viewProj;" in apply_edits(text, plan.edits)
    assert "MAT002" not in rules_of(apply_edits(text, plan.edits))


def test_existing_qualifiers_and_the_pragma_are_left_alone() -> None:
    explicit = "cbuffer C { row_major float4x4 a; column_major float4x4 b; };"
    assert plan_fixes(explicit).edits == []
    pragma = "#pragma pack_matrix(row_major)\ncbuffer C { float4x4 a; };"
    assert plan_fixes(pragma).edits == []


def test_only_option_selects_rules(corpus: Path) -> None:
    text = (corpus / "hlsl" / "collision.hlsl").read_text()
    assert plan_fixes(text, rules={"MAT002"}).rules == {"MAT002"}
    assert plan_fixes(text, rules={"BND001"}).rules == {"BND001"}
    assert plan_fixes(text, rules=set()).edits == []


def test_comments_and_strings_with_register_text_are_not_edited() -> None:
    text = (
        "// Texture2D old : register(t0);\n"
        "cbuffer C : register(b0) { row_major float4x4 m; };\n"
        "Texture2D tex : register(t0);\n"
    )
    plan = plan_fixes(text)
    assert [e.line for e in plan.edits] == [3]
    assert "// Texture2D old : register(t0);" in apply_edits(text, plan.edits)


def test_preprocessor_lines_before_a_declaration_stay_in_front() -> None:
    text = (
        '#include "common.hlsli"\n#define X 1\n'
        "cbuffer C : register(b0) { row_major float4x4 m; };\n"
        "Texture2D tex : register(t0);\n"
    )
    fixed = fix(text)
    assert '#include "common.hlsli"\n#define X 1\n' in fixed
    assert "[[vk::binding(1, 0)]] Texture2D tex : register(t0);" in fixed


def test_spaces_are_kept_in_the_binding_set() -> None:
    text = (
        "cbuffer C : register(b0, space1) { row_major float4x4 m; };\n"
        "Texture2D t : register(t0, space1);\n"
    )
    fixed = fix(text, rules={"BND001"})
    assert "[[vk::binding(1, 1)]] Texture2D t : register(t0, space1);" in fixed


def test_two_declarations_in_one_statement_are_skipped_not_guessed() -> None:
    text = (
        "cbuffer C : register(b0) { row_major float4x4 m; };\n"
        "Texture2D a : register(t0), b : register(t1);\n"
    )
    plan = plan_fixes(text, rules={"BND001"})
    assert plan.edits == []
    assert any("could not place an attribute safely" in reason for reason in plan.skipped)


def test_clashing_explicit_attributes_are_reported_not_fixed() -> None:
    text = "[[vk::binding(3)]] Texture2D a;\n[[vk::binding(3)]] Texture2D b;\n"
    plan = plan_fixes(text, rules={"BND001"})
    assert plan.edits == []
    assert any("clash" in reason for reason in plan.skipped)


def test_already_attributed_resources_are_never_touched() -> None:
    text = (
        "cbuffer C : register(b0) { row_major float4x4 m; };\n"
        "[[vk::binding(9, 0)]] Texture2D tex : register(t0);\n"
        "SamplerState s : register(s0);\n"
    )
    fixed = fix(text, rules={"BND001"})
    assert fixed.count("[[vk::binding(9, 0)]]") == 1
    assert "[[vk::binding(1, 0)]] SamplerState s" not in fixed or "BND001" not in rules_of(fixed)


def test_crlf_files_are_preserved() -> None:
    text = "cbuffer C : register(b0) { row_major float4x4 m; };\r\nTexture2D t : register(t0);\r\n"
    fixed = fix(text)
    assert fixed.count("\r\n") == 2
    assert "\n" not in fixed.replace("\r\n", "")


def test_clean_shaders_have_nothing_to_fix(corpus: Path) -> None:
    for name in ("pbr_clean.hlsl", "fullscreen_vs.hlsl"):
        assert plan_fixes((corpus / "lint" / name).read_text()).edits == []
