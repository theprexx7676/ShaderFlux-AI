"""``shaderflux config``: inspect the effective configuration."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from shaderflux.core.config import flatten_settings, load_settings

config_app = typer.Typer(help="Inspect configuration.", no_args_is_help=True)


@config_app.command("show")
def show(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Print the effective configuration and where each value came from."""
    loaded = load_settings()
    if json_output:
        typer.echo(loaded.model_dump_json(indent=2))
        return
    table = Table(title="Effective configuration")
    for column in ("Setting", "Value", "Source"):
        table.add_column(column, overflow="fold")
    values = flatten_settings(loaded.settings.model_dump(mode="json"))
    for key in sorted(values):
        table.add_row(key, str(values[key]), loaded.sources.get(key, "default"))
    Console().print(table)
    if not loaded.files:
        typer.echo("No configuration files found; using defaults.")
