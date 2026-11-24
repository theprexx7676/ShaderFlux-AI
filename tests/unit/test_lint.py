"""Tests for the lint engine, rule docs and the lint/explain commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.analysis.intrinsics import check_intrinsics, load_intrinsics, lookup
from shaderflux.analysis.lint import filter_findings, lint_file, lint_text, to_sarif
from shaderflux.analysis.rules import all_rules, get_rule
from shaderflux.cli.app import app
from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import Severity, ShaderLanguage

pytestmark = pytest.mark.unit

runner = CliRunner()
HLSL = ShaderLanguage.HLSL
GLSL = ShaderLanguage.GLSL


# ---- intrinsics -----------------------------------------------------------


def test_intrinsic_table_is_large_and_well_formed() -> None:
    entries = load_intrinsics()
    assert len(entries) >= 30
    assert {e.evidence for e in entries} <= {"verified", "documented", "unverified"}
    for entry in entries:
        assert entry.hlsl or entry.glsl
        if entry.flag:
            assert entry.rule
            assert entry.title
            assert entry.fix


def test_lookup_finds_entries_by_either_name() -> None:
    assert lookup("lerp")[0].glsl == "mix"
    assert lookup("mix")[0].hlsl == "lerp"
    assert lookup("nonexistent_intrinsic") == []


def test_fmod_and_mod_are_flagged_in_their_own_language() -> None:
    hlsl = check_intrinsics("float f(float a, float b) { return fmod(a, b); }", HLSL)
    glsl = check_intrinsics("float f(float a, float b) { return mod(a, b); }", GLSL)
    assert [f.rule for f in hlsl] == ["INT001"]
    assert [f.rule for f in glsl] == ["INT001"]
    assert hlsl[0].confidence is Confidence.HIGH  # verified with real SPIRV-Cross


def test_inverse_only_flagged_in_glsl() -> None:
    assert [f.rule for f in check_intrinsics("mat4 m = inverse(x);", GLSL)] == ["INT002"]
    assert check_intrinsics("float4x4 m = inverse(x);", HLSL) == []


def test_intrinsics_ignore_comments_and_identifiers() -> None:
    assert check_intrinsics("// fmod(a, b)\nfloat my_fmod(float a);", HLSL) == []
    assert check_intrinsics("float x = fmodulo(a);", HLSL) == []


def test_unverified_evidence_gives_low_confidence() -> None:
    (finding,) = check_intrinsics("float x = round(a);", HLSL)
    assert finding.rule == "INT003"
    assert finding.confidence is Confidence.LOW


# ---- rule docs ------------------------------------------------------------


def test_every_emitted_rule_is_documented() -> None:
    documented = set(all_rules())
    assert {"BND001", "BND002", "MAT001", "MAT002", "MAT003", "MAT004", "MAT005"} <= documented
    assert {"INT001", "INT002", "INT003"} <= documented
    for info in all_rules().values():
        assert info.title
        assert info.why
        assert info.fix
        assert info.evidence


def test_get_rule_is_case_insensitive() -> None:
    assert get_rule("bnd001") is not None
    assert get_rule("NOPE999") is None


# ---- engine ---------------------------------------------------------------


def test_lint_text_combines_rules_and_sorts() -> None:
    text = "cbuffer C : register(b0) { float4x4 m; };\nTexture2D t : register(t0);\n"
    rules = [f.rule for f in lint_text(text, HLSL, file="a.hlsl")]
    assert rules == ["BND001", "MAT002"]


def test_lint_text_target_any_skips_vulkan_binding_rules() -> None:
    text = "cbuffer C : register(b0) { row_major float4x4 m; };\nTexture2D t : register(t0);\n"
    assert [f.rule for f in lint_text(text, HLSL, vulkan=True)] == ["BND001"]
    assert lint_text(text, HLSL, vulkan=False) == []


def test_lint_file_finds_collisions_across_includes(tmp_path: Path) -> None:
    (tmp_path / "common.hlsli").write_text("cbuffer C : register(b0) { row_major float4x4 m; };\n")
    main = tmp_path / "main.hlsl"
    main.write_text(
        '#include "common.hlsli"\nTexture2D t : register(t0);\n'
        "float4 main() : SV_Target { return 0; }\n"
    )
    report = lint_file(main)
    (finding,) = report.findings
    assert finding.rule == "BND001"
    assert finding.file is not None
    assert finding.file.endswith("common.hlsli")  # the earliest declaration of the clash
    assert len(report.files) == 2


def test_lint_file_reports_missing_include_as_a_finding(tmp_path: Path) -> None:
    main = tmp_path / "main.hlsl"
    main.write_text('#include "nope.hlsli"\n')
    (finding,) = lint_file(main).findings
    assert finding.rule == "INC001"
    assert finding.severity is Severity.ERROR


def test_lint_file_rejects_unsupported_input(tmp_path: Path) -> None:
    module = tmp_path / "m.spv"
    module.write_bytes(b"\x03\x02\x23\x07")
    with pytest.raises(InvalidInputError, match="only HLSL and GLSL"):
        lint_file(module)


def test_filter_findings() -> None:
    low = Finding(rule="MAT003", severity=Severity.NOTE, message="x", confidence=Confidence.LOW)
    high = Finding(rule="BND001", severity=Severity.ERROR, message="y", confidence=Confidence.HIGH)
    assert filter_findings([low, high], ignore=["mat003"]) == [high]
    assert filter_findings([low, high], min_confidence=Confidence.MEDIUM) == [high]


def test_sarif_is_valid_and_located() -> None:
    finding = Finding(
        rule="BND001",
        severity=Severity.ERROR,
        message="clash",
        file="/p/a.hlsl",
        line=3,
        suggestion="shift",
    )
    document = json.loads(to_sarif([finding], tool_version="1.2.3"))
    assert document["version"] == "2.1.0"
    run = document["runs"][0]
    assert run["tool"]["driver"]["version"] == "1.2.3"
    (result,) = run["results"]
    assert (result["ruleId"], result["level"]) == ("BND001", "error")
    location = result["locations"][0]["physicalLocation"]
    assert location["region"]["startLine"] == 3
    assert "Fix: shift" in result["message"]["text"]


# ---- commands -------------------------------------------------------------


def test_lint_command_exit_codes(corpus: Path) -> None:
    clean = runner.invoke(app, ["lint", str(corpus / "hlsl" / "clean_matrix.hlsl")])
    assert clean.exit_code == 0
    assert "no problems" in clean.output
    bad = runner.invoke(app, ["lint", str(corpus / "hlsl" / "collision.hlsl")])
    assert bad.exit_code == 1
    assert "BND001" in bad.output
    assert "[[vk::binding]]" in bad.output  # Rich must not swallow it as markup


def test_lint_fail_on_levels(corpus: Path) -> None:
    mixed = str(corpus / "hlsl" / "mixed_mul.hlsl")  # warning + notes, no error
    assert runner.invoke(app, ["lint", mixed]).exit_code == 0
    assert runner.invoke(app, ["lint", mixed, "--fail-on", "warning"]).exit_code == 1
    assert runner.invoke(app, ["lint", mixed, "--fail-on", "never"]).exit_code == 0


def test_lint_json_and_sarif_outputs(corpus: Path) -> None:
    shader = str(corpus / "hlsl" / "collision.hlsl")
    data = json.loads(runner.invoke(app, ["lint", shader, "--json"]).stdout)
    assert data[0]["rule"] == "BND001"
    sarif = json.loads(runner.invoke(app, ["lint", shader, "--sarif"]).stdout)
    assert sarif["runs"][0]["results"]


def test_lint_ignore_and_target(corpus: Path) -> None:
    shader = str(corpus / "hlsl" / "collision.hlsl")
    assert runner.invoke(app, ["lint", shader, "--ignore", "BND001"]).exit_code == 0
    assert runner.invoke(app, ["lint", shader, "--target", "any"]).exit_code == 0


def test_lint_glsl_file(corpus: Path) -> None:
    result = runner.invoke(app, ["lint", str(corpus / "glsl" / "matrices.vert")])
    assert result.exit_code == 0
    assert "MAT004" in result.output
    assert "MAT005" in result.output


def test_lint_missing_file_is_a_usage_error() -> None:
    result = runner.invoke(app, ["lint", "nope.hlsl"])
    assert result.exit_code == 2


def test_explain_lists_and_details_rules() -> None:
    listing = runner.invoke(app, ["explain"])
    assert listing.exit_code == 0
    assert "BND001" in listing.output
    detail = runner.invoke(app, ["explain", "bnd001"])
    assert detail.exit_code == 0
    assert "Why it matters" in detail.output
    assert "[[vk::binding" in detail.output
    unknown = runner.invoke(app, ["explain", "ZZZ"])
    assert unknown.exit_code == 2


# ---- glob expansion (Windows shells and bash 3.2 do not expand ** themselves) ----------


def test_expand_patterns_handles_recursive_globs_literals_and_duplicates(tmp_path: Path) -> None:
    from shaderflux.source.patterns import expand_patterns

    (tmp_path / "a" / "b").mkdir(parents=True)
    first, second = tmp_path / "a" / "one.hlsl", tmp_path / "a" / "b" / "two.hlsl"
    first.write_text("x")
    second.write_text("x")
    (tmp_path / "a" / "ignore.txt").write_text("x")

    found = expand_patterns([Path(str(tmp_path / "**" / "*.hlsl"))])
    assert found == sorted([first, second])
    # a name that exists is literal; duplicates are removed; order is kept
    assert expand_patterns([first, Path(str(tmp_path / "a" / "*.hlsl")), first]) == [first]
    # a plain missing name passes through, so the usual "no such file" error is reported
    assert expand_patterns([Path("missing.hlsl")]) == [Path("missing.hlsl")]


def test_expand_patterns_reports_a_pattern_that_matches_nothing(tmp_path: Path) -> None:
    from shaderflux.source.patterns import expand_patterns

    with pytest.raises(InvalidInputError, match="no shader files matched"):
        expand_patterns([Path(str(tmp_path / "*.hlsl"))])
    (tmp_path / "dir.hlsl").mkdir()  # a directory is not a shader file
    with pytest.raises(InvalidInputError, match="no shader files matched"):
        expand_patterns([Path(str(tmp_path / "*.hlsl"))])


def test_lint_command_expands_quoted_patterns(tmp_path: Path, corpus: Path) -> None:
    import shutil

    (tmp_path / "s").mkdir()
    shutil.copy(corpus / "hlsl" / "clean_matrix.hlsl", tmp_path / "s" / "a.hlsl")
    shutil.copy(corpus / "hlsl" / "clean_matrix.hlsl", tmp_path / "s" / "b.hlsl")
    result = runner.invoke(app, ["lint", str(tmp_path / "s" / "*.hlsl")])
    assert result.exit_code == 0
    assert "in 2 file(s)" in result.output
