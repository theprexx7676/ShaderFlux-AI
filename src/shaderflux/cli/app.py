"""Entry point for the ``shaderflux`` command."""

from __future__ import annotations

import typer

from shaderflux import __version__
from shaderflux.cli.config_cmd import config_app
from shaderflux.cli.doctor import doctor_command
from shaderflux.cli.lint_cmd import explain_command, lint_command
from shaderflux.cli.translate_cmd import translate_command

app = typer.Typer(
    name="shaderflux",
    help="An assistant for porting shaders to PC.",
    no_args_is_help=True,
    add_completion=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"shaderflux {__version__}")
        raise typer.Exit()


app.command("doctor")(doctor_command)
app.command("translate")(translate_command)
app.command("lint")(lint_command)
app.command("explain")(explain_command)
app.add_typer(config_app, name="config")


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """ShaderFlux-AI command-line interface."""


def main() -> None:
    """Console-script entry point."""
    app()
