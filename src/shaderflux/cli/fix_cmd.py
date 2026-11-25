"""``shaderflux fix``: mechanical fixes for lint findings. No AI, no key, no network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape

from shaderflux.analysis.autofix import FIXABLE_RULES
from shaderflux.cli.errors import EXIT_FAILED, EXIT_OK, EXIT_USAGE, handle_errors
from shaderflux.core.config import load_settings
from shaderflux.core.errors import InvalidInputError
from shaderflux.source.inputs import parse_stage_name
from shaderflux.source.patterns import expand_patterns
from shaderflux.workflows.fix_file import FixOutcome, FixRequest, VerifyStatus, run_fix


def _show(outcome: FixOutcome, console: Console) -> None:
    name = outcome.path.name
    if not outcome.plan.edits:
        console.print(f"{escape(name)}: nothing to fix", highlight=False)
    for edit in outcome.plan.edits:
        console.print(
            f"  line {edit.line}  [bold]{edit.rule}[/]  {escape(edit.description)}",
            highlight=False,
        )
    for note in outcome.notes:
        console.print(f"  [yellow]not fixed:[/] {escape(note)}", highlight=False)


def _fix_one(path: Path, request_args: dict[str, Any], *, check: bool, console: Console) -> int:
    """Fix one file and print the result. Returns the exit code for this file."""
    try:
        outcome = run_fix(FixRequest(input_file=path, **request_args))
    except InvalidInputError as exc:
        console.print(f"[red]error:[/] {escape(str(exc))}", highlight=False)
        return EXIT_USAGE
    _show(outcome, console)
    if outcome.changed and outcome.written_to is None:
        typer.echo(outcome.diff, nl=False)
    if outcome.written_to is not None:
        console.print(f"wrote {escape(str(outcome.written_to))}", highlight=False)
    elif outcome.changed and not check:
        console.print("[dim]dry run: nothing was changed (use --write or --out)[/]")
    if outcome.changed and not outcome.complete:
        console.print(
            f"[yellow]{len(outcome.remaining)} finding(s) of the selected rules remain[/]",
            highlight=False,
        )
    verification = outcome.verification
    if verification is not None:
        label = {
            VerifyStatus.OK: "[green]verified[/]",
            VerifyStatus.NOT_RUN: "[yellow]not verified[/]",
        }.get(verification.status, "[red]verification failed[/]")
        console.print(f"{label}: {escape(verification.detail)}", highlight=False)
        if verification.status is VerifyStatus.NOT_RUN:
            return EXIT_USAGE
        if verification.status is not VerifyStatus.OK:
            return EXIT_FAILED
    if check and outcome.changed:
        return EXIT_FAILED
    return EXIT_OK


@handle_errors
def fix_command(
    files: list[Path] = typer.Argument(
        ..., help="HLSL files to fix. Glob patterns such as 'shaders/**/*.hlsl' work everywhere."
    ),
    only: list[str] = typer.Option(
        [], "--only", help=f"Fix only this rule (repeatable). Fixable: {', '.join(FIXABLE_RULES)}."
    ),
    include: list[Path] = typer.Option([], "-I", help="Include directory (repeatable)."),
    write: bool = typer.Option(False, "--write", help="Change the file in place."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write the fixed copy here."),
    force: bool = typer.Option(False, "--force", help="Overwrite --out if it exists."),
    verify: bool = typer.Option(
        False,
        "--verify",
        help="Recompile the fixed shader with DXC and check that no bindings are shared. "
        "Refuses to write a fix that stops a compiling shader from compiling.",
    ),
    stage: str | None = typer.Option(None, "--stage", "-s", help="For --verify: fragment, ..."),
    entry: str = typer.Option("main", "--entry", "-e", help="For --verify: entry point."),
    check: bool = typer.Option(
        False, "--check", help="Change nothing; exit 1 if there is anything to fix."
    ),
) -> None:
    """Fix the porting traps that can be fixed mechanically (insertions only).

    Shows a diff and changes nothing unless you pass --write or --out. Needs no API key.
    """
    settings = load_settings().settings
    if check and (write or out is not None):
        typer.echo(
            "error: --check changes nothing, so it cannot be used with --write/--out", err=True
        )
        raise typer.Exit(code=EXIT_USAGE)
    paths = expand_patterns(files)
    if out is not None and len(paths) > 1:
        typer.echo("error: --out takes one input file; use --write for several", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    if (stage or entry != "main") and not verify:
        typer.echo("error: --stage and --entry only make sense together with --verify", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    request_args: dict[str, Any] = {
        "rules": [r.upper() for r in only] or None,
        "include_dirs": [*settings.include_dirs, *include],
        "write": write,
        "out": out,
        "force": force,
        "verify": verify,
        "stage": parse_stage_name(stage) if stage else None,
        "entry_point": entry,
        "tool_paths": settings.tools,
    }
    console = Console(stderr=True, soft_wrap=True)
    worst = EXIT_OK
    for path in paths:
        if len(paths) > 1:
            console.print(f"[bold]{escape(str(path))}[/]", highlight=False)
        worst = max(worst, _fix_one(path, request_args, check=check, console=console))
    raise typer.Exit(code=worst)
