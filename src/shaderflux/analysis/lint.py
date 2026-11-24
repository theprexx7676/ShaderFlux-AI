"""The lint engine: run every rule on a shader and its includes."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from shaderflux.analysis.bindings import (
    HlslBinding,
    binding_findings,
    parse_hlsl_bindings,
    propose_policy,
)
from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.analysis.intrinsics import check_intrinsics
from shaderflux.analysis.limits import exceeds_limits, skipped_finding
from shaderflux.analysis.matrix_rules import check_matrices
from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import Severity, ShaderLanguage
from shaderflux.pipeline.includes import build_include_graph
from shaderflux.pipeline.inputs import decode_text, detect_language

_SEVERITY_RANK = {Severity.NOTE: 0, Severity.WARNING: 1, Severity.ERROR: 2}


class LintReport(BaseModel):
    files: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)

    def count(self, severity: Severity) -> int:
        return sum(1 for f in self.findings if f.severity is severity)

    def at_or_above(self, severity: Severity) -> list[Finding]:
        return [f for f in self.findings if _SEVERITY_RANK[f.severity] >= _SEVERITY_RANK[severity]]


def lint_text(
    text: str, language: ShaderLanguage, *, file: str | None = None, vulkan: bool = True
) -> list[Finding]:
    """Lint a single piece of source (no include handling)."""
    too_big = exceeds_limits(text)
    if too_big:
        return [skipped_finding(too_big, file)]
    findings: list[Finding] = []
    if language is ShaderLanguage.HLSL and vulkan:
        findings += binding_findings(
            propose_policy(parse_hlsl_bindings(text, file=file)), file=file
        )
    findings += check_matrices(text, language, file=file)
    findings += check_intrinsics(text, language, file=file)
    return sorted(findings, key=lambda f: (f.file or "", f.line or 0, f.rule))


def lint_file(
    path: Path,
    *,
    language: ShaderLanguage | None = None,
    include_dirs: Sequence[Path] = (),
    vulkan: bool = True,
) -> LintReport:
    """Lint a shader file and everything it ``#include``s."""
    path = Path(path)
    if not path.is_file():
        raise InvalidInputError(f"no such file: {path}")
    language = language or detect_language(path)
    if language not in (ShaderLanguage.HLSL, ShaderLanguage.GLSL):
        raise InvalidInputError(f"cannot lint {path.name}: only HLSL and GLSL source is supported")

    graph = build_include_graph(path, include_dirs)
    report = LintReport(files=[str(f) for f in graph.files])
    for diagnostic in graph.diagnostics:
        report.findings.append(
            Finding(
                rule="INC001",
                severity=diagnostic.severity,
                message=diagnostic.message,
                file=diagnostic.file,
                line=diagnostic.line,
                confidence=Confidence.HIGH,
            )
        )

    all_bindings: list[HlslBinding] = []
    for file in graph.files:
        text = decode_text(file.read_bytes(), name=file.name)
        name = str(file)
        too_big = exceeds_limits(text)
        if too_big:
            report.findings.append(skipped_finding(too_big, name))
            continue
        report.findings += check_matrices(text, language, file=name)
        report.findings += check_intrinsics(text, language, file=name)
        if language is ShaderLanguage.HLSL and vulkan:
            all_bindings += parse_hlsl_bindings(text, file=name)
    if all_bindings:
        report.findings += binding_findings(propose_policy(all_bindings))

    report.findings.sort(key=lambda f: (f.file or "", f.line or 0, f.rule))
    return report


def filter_findings(
    findings: Iterable[Finding],
    *,
    ignore: Iterable[str] = (),
    min_confidence: Confidence = Confidence.LOW,
) -> list[Finding]:
    order = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
    ignored = {rule.upper() for rule in ignore}
    return [
        f
        for f in findings
        if f.rule.upper() not in ignored and order[f.confidence] >= order[min_confidence]
    ]


def to_sarif(findings: Iterable[Finding], *, tool_version: str = "0") -> str:
    """Render findings as SARIF 2.1.0 for GitHub code scanning and IDEs."""
    levels = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.NOTE: "note"}
    results = []
    for f in findings:
        result: dict[str, object] = {
            "ruleId": f.rule,
            "level": levels[f.severity],
            "message": {"text": f.message + (f" Fix: {f.suggestion}" if f.suggestion else "")},
        }
        if f.file:
            region = {"startLine": f.line} if f.line else {}
            result["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": Path(f.file).as_posix()},
                        **({"region": region} if region else {}),
                    }
                }
            ]
        results.append(result)
    rule_ids = sorted({str(r["ruleId"]) for r in results})
    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "shaderflux",
                        "version": tool_version,
                        "informationUri": "https://github.com/theprexx7676/ShaderFlux-AI",
                        "rules": [{"id": rule_id} for rule_id in rule_ids],
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(document, indent=2)
