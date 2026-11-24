"""``shaderflux doctor``: report which external tools are available."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from shaderflux.tools.discovery import ToolState, doctor

_STYLE = {
    ToolState.OK: "green",
    ToolState.UNKNOWN_VERSION: "yellow",
    ToolState.OLD: "red",
    ToolState.MISSING: "red",
}


def doctor_command(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Check that the external shader tools are installed."""
    report = doctor()
    if json_output:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit(code=0 if report.ok else 1)

    console = Console()
    table = Table(title="ShaderFlux tool check")
    for column in ("Tool", "Status", "Version", "Path / hint"):
        table.add_column(column, overflow="fold")
    for tool in report.tools:
        label = tool.state.value + (" (optional)" if tool.optional and tool.state != "ok" else "")
        detail = tool.path or tool.hint or ""
        table.add_row(
            tool.key,
            f"[{_STYLE[tool.state]}]{label}[/]",
            tool.version or "-",
            detail,
        )
    console.print(table)
    for note in report.notes:
        console.print(f"[yellow]note:[/] {note}")
    if report.ok:
        console.print("[green]All required tools are available.[/]")
    else:
        console.print("[red]Some required tools are missing. See the hints above.[/]")
    raise typer.Exit(code=0 if report.ok else 1)
