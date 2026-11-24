"""Tests for verdicts and reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.analysis.findings import Finding
from shaderflux.cli.app import app
from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    StageResult,
    Target,
    ToolInfo,
    TranslationResult,
)
from shaderflux.reporting.report import build_report, render_markdown, write_report
from shaderflux.verify.levels import Label, Level, assess

pytestmark = pytest.mark.unit


def stage(name: str, tool: str = "t", *, ok: bool = True, warn: str | None = None) -> StageResult:
    diagnostics = [Diagnostic(severity=Severity.WARNING, message=warn)] if warn else []
    return StageResult(
        name=name, ok=ok, tool=ToolInfo(name=tool, version="1"), diagnostics=diagnostics
    )


HLSL = Target(language=ShaderLanguage.HLSL, version="50", environment="vulkan1.2")
GLSL = Target(language=ShaderLanguage.GLSL)
SPIRV = Target(language=ShaderLanguage.SPIRV)


def full_stages(final: str = "recompile generated glsl") -> list[StageResult]:
    return [
        stage("compile glsl", "glslang"),
        stage("validate spirv", "spirv-val"),
        stage("convert to glsl", "cross"),
        stage(final, "glslc"),
    ]


def test_failed_translation() -> None:
    result = TranslationResult(ok=False, stages=[stage("compile glsl", ok=False)])
    verdict = assess(result, HLSL)
    assert (verdict.level, verdict.label) == (Level.FAILED, Label.FAILED)
    assert "compile glsl" in verdict.not_checked[0]


def test_fully_checked_text_output() -> None:
    verdict = assess(TranslationResult(ok=True, stages=full_stages()), GLSL)
    assert (verdict.level, verdict.label) == (Level.OUTPUT_CHECKED, Label.CHECKED)
    assert any("compiled again" in c for c in verdict.checked)
    assert any("same pixels" in n for n in verdict.not_checked)  # always admitted


def test_skipped_recheck_is_only_partly_checked() -> None:
    stages = full_stages()
    stages[-1] = stage("recompile generated hlsl", "none", warn="dxc was not found, so ...")
    verdict = assess(TranslationResult(ok=True, stages=stages), HLSL)
    assert (verdict.level, verdict.label) == (Level.VALIDATED, Label.PARTLY_CHECKED)
    assert any("dxc was not found" in n for n in verdict.not_checked)


def test_missing_validator_is_reported() -> None:
    stages = [
        stage("compile glsl", "glslang"),
        stage("validate spirv", "none"),
        stage("convert to glsl"),
    ]
    verdict = assess(TranslationResult(ok=True, stages=stages), GLSL)
    assert verdict.level is Level.COMPILED
    assert any("SPIR-V validation" in n for n in verdict.not_checked)


def test_spirv_target_is_complete_once_validated() -> None:
    stages = [stage("compile glsl", "glslang"), stage("validate spirv", "spirv-val")]
    verdict = assess(TranslationResult(ok=True, stages=stages), SPIRV)
    assert (verdict.level, verdict.label) == (Level.VALIDATED, Label.CHECKED)


def test_msl_output_is_never_fully_checked() -> None:
    stages = [
        stage("compile glsl", "g"),
        stage("validate spirv", "v"),
        stage("convert to msl", "c"),
    ]
    verdict = assess(TranslationResult(ok=True, stages=stages), Target(language=ShaderLanguage.MSL))
    assert verdict.label is Label.PARTLY_CHECKED
    assert any("MSL" in n for n in verdict.not_checked)


def source(path: Path | None = None) -> ShaderSource:
    return ShaderSource(
        path=path, text="void main() {}", language=ShaderLanguage.GLSL, stage=ShaderStage.FRAGMENT,
        defines={"A": "1"},
    )  # fmt: skip


def make_report(**kwargs: object):  # type: ignore[no-untyped-def]
    result = TranslationResult(ok=True, stages=full_stages(), run_id="abc123")
    return build_report(
        source(Path("/home/alice/secret-project/main.frag")), GLSL, result,
        now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), **kwargs,
    )  # fmt: skip


def test_report_has_names_and_hashes_but_no_absolute_paths() -> None:
    report = make_report()
    text = report.model_dump_json()
    assert report.input.file == "main.frag"
    assert "alice" not in text
    assert "secret-project" not in text
    assert report.created_at == "2026-01-02T03:04:05+00:00"
    assert report.input.defines == {"A": "1"}
    assert len(report.input.sha256) == 64


def test_report_json_round_trips() -> None:
    report = make_report(findings=[Finding(rule="MAT002", severity=Severity.NOTE, message="m")])
    restored = type(report).model_validate_json(report.model_dump_json())
    assert restored == report
    assert restored.porting_risks is not None


def test_markdown_contains_the_honest_sections() -> None:
    markdown = render_markdown(make_report(findings=[]))
    for heading in (
        "## What was checked",
        "## What was not checked",
        "## Steps",
        "## Porting risks",
    ):
        assert heading in markdown
    assert "checked (level 3: output checked)" in markdown
    assert "No known porting traps found (a heuristic check, not a proof)" in markdown
    assert "does not prove the shader is correct" in markdown


def test_skipped_steps_are_labelled_skipped() -> None:
    stages = [stage("compile glsl", "g"), stage("recompile generated hlsl", "none", warn="no dxc")]
    result = TranslationResult(ok=True, stages=stages)
    markdown = render_markdown(build_report(source(), HLSL, result))
    assert "| recompile generated hlsl | skipped |" in markdown


def test_write_report_formats_and_overwrites(tmp_path: Path) -> None:
    report = make_report()
    as_json = write_report(report, tmp_path / "sub" / "r.json")
    assert json.loads(as_json.read_text())["schema_version"] == "1"
    as_md = write_report(report, tmp_path / "r.md")
    assert as_md.read_text().startswith("# ShaderFlux report")
    write_report(report, tmp_path / "r.md")  # replacing an old report is fine
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r.md", "sub"]
    with pytest.raises(InvalidInputError, match="directory"):
        write_report(report, tmp_path)


def test_no_report_is_written_without_the_flag(corpus: Path, tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["translate", str(corpus / "glsl" / "textured.frag"), "--to", "hlsl"]
    )
    assert "report written" not in result.output
