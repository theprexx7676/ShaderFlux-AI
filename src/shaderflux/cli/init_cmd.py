"""``shaderflux init``: write a starter config (and optionally a GitHub workflow)."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from shaderflux.cli.errors import EXIT_OK, handle_errors
from shaderflux.workflows.init_project import InitRequest, run_init


@handle_errors
def init_command(
    directory: Path = typer.Argument(Path("."), help="Project root to write into."),
    shaders: str = typer.Option("shaders", "--shaders", help="Where your shaders live."),
    github: bool = typer.Option(
        False, "--github", help="Also write a GitHub Actions workflow that lints shaders on PRs."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
) -> None:
    """Write a starter shaderflux.toml (and with --github, a lint workflow).

    Needs no API key. Existing files are never overwritten without --force.
    """
    outcome = run_init(
        InitRequest(directory=directory, shaders_dir=shaders, github=github, force=force)
    )
    console = Console(stderr=True, soft_wrap=True)
    for path in outcome.written:
        console.print(f"wrote {escape(str(path))}", highlight=False)
    pattern = f"{shaders.strip().rstrip('/')}/**/*.hlsl"
    console.print(f"next: shaderflux lint '{escape(pattern)}'", highlight=False)
    raise typer.Exit(code=EXIT_OK)
