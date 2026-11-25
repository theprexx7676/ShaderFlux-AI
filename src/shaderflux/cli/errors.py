"""Exit codes and error reporting for the command line."""

from __future__ import annotations

import sys
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

import typer

from shaderflux.core.errors import (
    InvalidInputError,
    ShaderFluxError,
    ToolFailedError,
    ToolMissingError,
    UnsupportedRouteError,
)

# Documented in plan task 8.2.3.
EXIT_OK = 0
EXIT_FAILED = 1  # the translation or verification did not succeed
EXIT_USAGE = 2  # bad input, bad options, missing tools
EXIT_TOOL = 3  # a tool or the LLM failed while running

P = ParamSpec("P")
R = TypeVar("R")


def exit_code_for(error: ShaderFluxError) -> int:
    if isinstance(error, InvalidInputError | UnsupportedRouteError | ToolMissingError):
        return EXIT_USAGE
    if isinstance(error, ToolFailedError):
        return EXIT_TOOL
    return EXIT_TOOL


def handle_errors(func: Callable[P, R]) -> Callable[P, R]:
    """Turn expected errors into a one-line message and a meaningful exit code."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except ShaderFluxError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=exit_code_for(exc)) from None

    return wrapper


def eprint(text: str = "") -> None:
    print(text, file=sys.stderr)
