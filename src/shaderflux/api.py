"""The public Python API.

Everything the command line does is available here without the command line::

    from shaderflux.api import TranslateRequest, ShaderLanguage, run_translate, lint_file

    report = lint_file("shaders/lighting.hlsl")
    for finding in report.findings:
        print(finding.format())

    outcome = run_translate(
        TranslateRequest(input_file=Path("pass.frag"), target_language=ShaderLanguage.HLSL)
    )
    print(outcome.result.output_text if outcome.result.ok else outcome.result.diagnostics)

Names not exported here are internal and may change. Nothing in this module prints or exits.
"""

from __future__ import annotations

from shaderflux import __version__
from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.analysis.lint import LintReport, lint_file, lint_text
from shaderflux.analysis.rules import RuleInfo, all_rules, get_rule
from shaderflux.core.errors import (
    InvalidInputError,
    LlmError,
    ShaderFluxError,
    ToolFailedError,
    ToolMissingError,
    UnsupportedRouteError,
)
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    Target,
    TranslationResult,
)
from shaderflux.reporting.report import Report, build_report, render_markdown
from shaderflux.tools.discovery import DoctorReport, doctor
from shaderflux.verify.levels import Assessment, assess
from shaderflux.workflows.translate_file import (
    TranslateOutcome,
    TranslateRequest,
    check_request,
    run_translate,
)

__all__ = [
    "Assessment",
    "Confidence",
    "Diagnostic",
    "DoctorReport",
    "Finding",
    "InvalidInputError",
    "LintReport",
    "LlmError",
    "Report",
    "RuleInfo",
    "Severity",
    "ShaderFluxError",
    "ShaderLanguage",
    "ShaderSource",
    "ShaderStage",
    "Target",
    "ToolFailedError",
    "ToolMissingError",
    "TranslateOutcome",
    "TranslateRequest",
    "TranslationResult",
    "UnsupportedRouteError",
    "__version__",
    "all_rules",
    "assess",
    "build_report",
    "check_request",
    "doctor",
    "get_rule",
    "lint_file",
    "lint_text",
    "render_markdown",
    "run_translate",
]
