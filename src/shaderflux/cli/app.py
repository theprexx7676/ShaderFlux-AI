"""Entry point for the ``shaderflux`` command."""

from __future__ import annotations

import typer

from shaderflux import __version__

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
