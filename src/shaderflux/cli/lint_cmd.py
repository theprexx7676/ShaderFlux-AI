"""``shaderflux lint`` and ``shaderflux explain``."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from shaderflux import __version__
from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.analysis.lint import LintReport, filter_findings, lint_file, to_sarif
from shaderflux.analysis.rules import all_rules, get_rule
from shaderflux.cli.errors import EXIT_FAILED, EXIT_OK, EXIT_USAGE, handle_errors
from shaderflux.core.config import load_settings
from shaderflux.core.models import Severity
from shaderflux.source.inputs import parse_language_name
from shaderflux.source.patterns import expand_patterns


class FailOn(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"
    NEVER = "never"


class Target(StrEnum):
    VULKAN = "vulkan"
    ANY = "any"


_COLOR = {Severity.ERROR: "red", Severity.WARNING: "yellow", Severity.NOTE: "cyan"}


def _print_finding(console: Console, finding: Finding) -> None:
    where = ""
    if finding.file:
        where = Path(finding.file).name + (f":{finding.line}" if finding.line else "")
    color = _COLOR[finding.severity]
    console.print(
        f"[bold]{where}[/]  [{color}]{finding.severity.value}[/]  [bold]{finding.rule}[/]  "
        f"{escape(finding.message)}",
        highlight=False,
    )
    if finding.suggestion:
        console.print(f"    [green]fix:[/] {escape(finding.suggestion)}", highlight=False)
    if finding.confidence is Confidence.LOW:
        console.print("    [dim]low confidence: heuristic, please check[/]", highlight=False)


def _summary(report: LintReport, findings: list[Finding]) -> str:
    counts = {s: sum(1 for f in findings if f.severity is s) for s in Severity}
    parts = [f"{n} {s.value}{'s' if n != 1 else ''}" for s, n in counts.items() if n]
    return ", ".join(parts) if parts else "no problems"


@handle_errors
def lint_command(
    files: list[Path] = typer.Argument(
        ...,
        help="Shader files to check. Glob patterns such as 'shaders/**/*.hlsl' work everywhere.",
    ),
    from_: str | None = typer.Option(None, "--from", help="Source language (default: detect)."),
    include: list[Path] = typer.Option([], "-I", help="Include directory (repeatable)."),
    target: Target = typer.Option(Target.VULKAN, "--target", help="Porting target."),
    fail_on: FailOn = typer.Option(FailOn.ERROR, "--fail-on", help="Exit 1 at this severity."),
    ignore: list[str] = typer.Option([], "--ignore", help="Rule id to skip (repeatable)."),
    json_output: bool = typer.Option(False, "--json", help="Print findings as JSON."),
    sarif: bool = typer.Option(False, "--sarif", help="Print SARIF for code-scanning tools."),
    min_confidence: Confidence = typer.Option(
        Confidence.LOW, "--min-confidence", help="Hide findings below this confidence."
    ),
) -> None:
    """Check shaders for known porting traps, without changing them."""
    settings = load_settings().settings
    language = parse_language_name(from_) if from_ else None
    files = expand_patterns(files)

    findings: list[Finding] = []
    reports: list[LintReport] = []
    for path in files:
        report = lint_file(
            path,
            language=language,
            include_dirs=[*settings.include_dirs, *include],
            vulkan=target is Target.VULKAN,
        )
        report.findings = filter_findings(
            report.findings, ignore=ignore, min_confidence=min_confidence
        )
        reports.append(report)
        findings += report.findings

    if sarif:
        typer.echo(to_sarif(findings, tool_version=__version__))
    elif json_output:
        typer.echo(
            "[" + ",".join(f.model_dump_json() for f in findings) + "]" if findings else "[]"
        )
    else:
        console = Console()
        for finding in findings:
            _print_finding(console, finding)
        console.print()
        console.print(f"[bold]{_summary(reports[0], findings)}[/] in {len(files)} file(s).")
        if findings:
            console.print("Run [bold]shaderflux explain <RULE>[/] for the why and how to fix.")
        else:
            console.print(
                "[dim]No known porting traps found. This is a heuristic check and does not "
                "prove the shader is correct.[/]"
            )

    if fail_on is FailOn.NEVER:
        raise typer.Exit(code=EXIT_OK)
    threshold = Severity(fail_on.value)
    failing = [f for r in reports for f in r.at_or_above(threshold)]
    raise typer.Exit(code=EXIT_FAILED if failing else EXIT_OK)


def explain_command(
    rule: str | None = typer.Argument(None, help="Rule id such as BND001. Omit to list all."),
) -> None:
    """Explain a lint rule: why it matters, how to fix it, and how sure we are."""
    console = Console()
    if rule is None:
        console.print("[bold]Rules[/]")
        for entry in all_rules().values():
            console.print(f"  [bold]{entry.id}[/]  {escape(entry.title)}", highlight=False)
        console.print("\nRun [bold]shaderflux explain <RULE>[/] for details.")
        return
    info = get_rule(rule)
    if info is None:
        typer.echo(f"error: unknown rule {rule!r}; run 'shaderflux explain' to list them", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    console.print(f"[bold]{info.id}[/]  {escape(info.title)}\n", highlight=False)
    console.print(f"[bold]Why it matters[/]\n  {escape(info.why)}\n", highlight=False)
    console.print(f"[bold]How to fix it[/]\n  {escape(info.fix)}\n", highlight=False)
    console.print(f"[bold]How sure are we[/]\n  {escape(info.evidence)}", highlight=False)
    for link in info.links:
        console.print(f"  [dim]{escape(link)}[/]", highlight=False)
