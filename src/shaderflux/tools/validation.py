"""Validation of user-supplied values before they reach a tool's command line.

Everything that ends up as an argument to a compiler passes through here, so an odd
macro name, entry point or file name cannot become an option or inject text.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import ShaderSource

_DEFINE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENTRY_POINT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SPIRV_ENV = re.compile(
    r"^(vulkan1\.[0-4](spirv1\.[0-6])?|spirv1\.[0-6]|universal1\.[0-6]|opengl)$"
)


def check_define_name(name: str) -> str:
    if not _DEFINE_NAME.match(name):
        raise InvalidInputError(f"invalid macro name: {name!r}")
    return name


def check_define_value(name: str, value: str) -> str:
    if "\0" in value or "\n" in value or "\r" in value:
        raise InvalidInputError(f"macro {name} has a value with a control character")
    return value


def define_args(defines: Mapping[str, str | None], style: str = "-D{}") -> list[str]:
    """Render ``{"A": "1", "B": None}`` as ``["-DA=1", "-DB"]``."""
    args: list[str] = []
    for name, value in defines.items():
        check_define_name(name)
        if value is None:
            args.append(style.format(name))
        else:
            args.append(style.format(f"{name}={check_define_value(name, value)}"))
    return args


def check_entry_point(entry: str) -> str:
    if not _ENTRY_POINT.match(entry):
        raise InvalidInputError(f"invalid entry point name: {entry!r}")
    return entry


def check_spirv_env(environment: str | None) -> str | None:
    if environment is None:
        return None
    if not _SPIRV_ENV.match(environment):
        raise InvalidInputError(
            f"unsupported target environment {environment!r} (examples: vulkan1.2, spirv1.5)"
        )
    return environment


def display_name(source: ShaderSource, default: str) -> str:
    """File name used for the temporary copy, so diagnostics show something meaningful.

    A name that starts with ``-`` would be read by the compiler as an option, so
    leading dashes are removed. Anything unusual in the name becomes ``_``.
    """
    if source.path is not None and source.path.name:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", source.path.name).lstrip("-")
        if name and not name.startswith("."):
            return name
    return default
