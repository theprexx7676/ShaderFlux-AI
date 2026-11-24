"""``shaderflux fix``: mechanical fixes for lint findings. No AI, no key, no network."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from shaderflux.analysis.autofix import FIXABLE_RULES
from shaderflux.cli.errors import EXIT_FAILED, EXIT_OK, handle_errors
from shaderflux.core.config import load_settings
from shaderflux.workflows.fix_file import FixOutcome, FixRequest, run_fix


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


@handle_errors
def fix_command(
    file: Path = typer.Argument(..., help="HLSL file to fix."),
    only: list[str] = typer.Option(
        [], "--only", help=f"Fix only this rule (repeatable). Fixable: {', '.join(FIXABLE_RULES)}."
    ),
    include: list[Path] = typer.Option([], "-I", help="Include directory (repeatable)."),
    write: bool = typer.Option(False, "--write", help="Change the file in place."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write the fixed copy here."),
    force: bool = typer.Option(False, "--force", help="Overwrite --out if it exists."),
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
        raise typer.Exit(code=2)
    outcome = run_fix(
        FixRequest(
            input_file=file,
            rules=[r.upper() for r in only] or None,
            include_dirs=[*settings.include_dirs, *include],
            write=write,
            out=out,
            force=force,
        )
    )
    console = Console(stderr=True, soft_wrap=True)
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
    if check and outcome.changed:
        raise typer.Exit(code=EXIT_FAILED)
    raise typer.Exit(code=EXIT_OK)
