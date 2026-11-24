"""Run reports: what was done, what was checked, and what was not.

A report records file *names* and content hashes, never absolute paths or secrets.
It does contain the shader's diagnostics and, after an AI-assisted repair, the diff,
so treat it like the shader itself.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from shaderflux import __version__
from shaderflux.analysis.findings import Finding
from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import (
    Diagnostic,
    ShaderSource,
    StageResult,
    Target,
    TranslationResult,
)
from shaderflux.llm.repair import Outcome, RepairResult
from shaderflux.verify.levels import Assessment, assess

SCHEMA_VERSION = "1"


class ReportInput(BaseModel):
    file: str
    language: str
    stage: str | None
    entry_point: str
    defines: dict[str, str | None]
    sha256: str


class ReportAttempt(BaseModel):
    number: int
    outcome: Outcome
    message: str
    errors_before: int
    errors_after: int | None
    diff: str


class ReportRepair(BaseModel):
    model: str
    prompt_version: str
    stop_reason: str
    fixed: bool
    attempts: list[ReportAttempt]
    diff: str
    calls: int
    input_tokens: int
    output_tokens: int


class Report(BaseModel):
    schema_version: str = SCHEMA_VERSION
    shaderflux_version: str = __version__
    created_at: str
    run_id: str | None
    ok: bool
    cached: bool
    input: ReportInput
    target: Target
    verdict: Assessment
    stages: list[StageResult]
    diagnostics: list[Diagnostic]
    porting_risks: list[Finding] | None = None
    repair: ReportRepair | None = None
    ai_assisted: bool = False
    notes: list[str] = Field(default_factory=list)


def build_report(
    source: ShaderSource,
    target: Target,
    result: TranslationResult,
    *,
    repair: RepairResult | None = None,
    findings: list[Finding] | None = None,
    now: datetime | None = None,
) -> Report:
    """Assemble a report. ``source`` is the *original* input (before any AI patch)."""
    created = (now or datetime.now(UTC)).replace(microsecond=0).isoformat()
    section: ReportRepair | None = None
    if repair is not None and repair.attempts:
        section = ReportRepair(
            model=repair.model,
            prompt_version=repair.prompt_version,
            stop_reason=repair.stop_reason,
            fixed=repair.ok,
            attempts=[
                ReportAttempt(
                    number=a.number,
                    outcome=a.outcome,
                    message=a.message,
                    errors_before=a.errors_before,
                    errors_after=a.errors_after,
                    diff=a.diff,
                )
                for a in repair.attempts
            ],
            diff=repair.diff,
            calls=repair.usage.calls,
            input_tokens=repair.usage.input_tokens,
            output_tokens=repair.usage.output_tokens,
        )
    ai_assisted = bool(repair is not None and repair.changed)
    notes = []
    if ai_assisted:
        notes.append("The shader was changed by an AI-proposed edit; review the diff before use.")
    if result.cached:
        notes.append("This result came from the cache; no tool ran this time.")
    return Report(
        created_at=created,
        run_id=result.run_id,
        ok=result.ok,
        cached=result.cached,
        input=ReportInput(
            file=source.path.name if source.path else "(stdin)",
            language=source.language.value,
            stage=source.stage.value if source.stage else None,
            entry_point=source.entry_point,
            defines=dict(source.defines),
            sha256=source.content_hash,
        ),
        target=target,
        verdict=assess(result, target),
        stages=result.stages,
        diagnostics=result.diagnostics,
        porting_risks=findings,
        repair=section,
        ai_assisted=ai_assisted,
        notes=notes,
    )


def _fence(text: str, language: str = "") -> str:
    return f"```{language}\n{text.rstrip()}\n```"


def render_markdown(report: Report) -> str:
    v = report.verdict
    lines = [
        "# ShaderFlux report",
        "",
        f"- **Result:** {'success' if report.ok else 'failed'}",
        f"- **Verdict:** {v.summary}",
        f"- **Input:** `{report.input.file}` ({report.input.language}"
        + (f", {report.input.stage}" if report.input.stage else "")
        + f") `sha256:{report.input.sha256[:12]}`",
        f"- **Target:** {report.target.language.value}"
        + (f" {report.target.version}" if report.target.version else "")
        + (f" ({report.target.environment})" if report.target.environment else ""),
        f"- **Created:** {report.created_at} by ShaderFlux {report.shaderflux_version}"
        + (f" (run {report.run_id})" if report.run_id else ""),
    ]
    if report.ai_assisted:
        lines.append("- **AI-assisted:** yes, review the diff below")
    for note in report.notes:
        lines.append(f"- _{note}_")

    lines += ["", "## What was checked", ""]
    lines += [f"- {item}" for item in v.checked] or ["- nothing"]
    lines += ["", "## What was not checked", ""]
    lines += [f"- {item}" for item in v.not_checked] or ["- nothing listed"]

    lines += ["", "## Steps", "", "| Step | Result | Tool | Time |", "| --- | --- | --- | --- |"]
    for stage in report.stages:
        tool = "-"
        if stage.tool and stage.tool.name != "none":
            tool = stage.tool.name + (f" {stage.tool.version}" if stage.tool.version else "")
        skipped = stage.tool is not None and stage.tool.name == "none"
        status = "skipped" if skipped else ("ok" if stage.ok else "FAILED")
        lines.append(f"| {stage.name} | {status} | {tool} | {stage.duration_s:.2f}s |")

    if report.diagnostics:
        lines += ["", "## Messages", ""]
        lines.append(_fence("\n".join(d.format() for d in report.diagnostics)))

    if report.porting_risks is not None:
        lines += ["", "## Porting risks", ""]
        if report.porting_risks:
            lines.append(_fence("\n".join(f.format() for f in report.porting_risks)))
            lines.append("")
            lines.append("Run `shaderflux explain <RULE>` for the reasoning behind each rule.")
        else:
            lines.append("No known porting traps found (a heuristic check, not a proof).")

    if report.repair is not None:
        r = report.repair
        lines += [
            "",
            "## AI-assisted repair",
            "",
            f"- **Outcome:** {'fixed' if r.fixed else 'not fixed'} ({r.stop_reason})",
            f"- **Model:** {r.model or 'unknown'}, prompt {r.prompt_version}",
            f"- **Usage:** {r.calls} call(s), {r.input_tokens} tokens in, {r.output_tokens} out",
            "",
        ]
        for a in r.attempts:
            after = "" if a.errors_after is None else f" -> {a.errors_after}"
            lines.append(
                f"{a.number}. {a.outcome.value}: errors {a.errors_before}{after}. {a.message}"
            )
        if r.diff:
            lines += ["", "### Change made to the shader", "", _fence(r.diff, "diff")]

    lines += [
        "",
        "---",
        "",
        "Generated by ShaderFlux-AI. This report does not prove the shader is correct.",
    ]
    return "\n".join(lines) + "\n"


def write_report(report: Report, path: Path) -> Path:
    """Write the report as Markdown (``.md``) or JSON (anything else), replacing any old report."""
    path = Path(path)
    text = (
        render_markdown(report)
        if path.suffix.lower() == ".md"
        else report.model_dump_json(indent=2) + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        raise InvalidInputError(f"{path} is a directory; give a file name for --report")
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
