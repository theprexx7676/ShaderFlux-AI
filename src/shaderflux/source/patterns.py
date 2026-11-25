"""Expanding glob patterns in command-line arguments."""

from __future__ import annotations

import glob
from pathlib import Path

from shaderflux.core.errors import InvalidInputError

_GLOB_MAGIC = ("*", "?", "[")


def expand_patterns(arguments: list[Path]) -> list[Path]:
    """Expand glob patterns (including ``**``) in the given arguments.

    Shells differ: Windows shells do not expand globs at all and bash 3.2 (the macOS
    default) has no ``**``. Doing it here makes every platform behave the same.
    A name that exists is taken literally; a plain missing name is passed through so
    the usual "no such file" error is reported; a pattern that matches nothing is an error.
    """
    expanded: list[Path] = []
    seen: set[Path] = set()
    for argument in arguments:
        text = str(argument)
        if argument.exists() or not any(ch in text for ch in _GLOB_MAGIC):
            matches = [argument]
        else:
            matches = sorted(Path(m) for m in glob.glob(text, recursive=True) if Path(m).is_file())
            if not matches:
                raise InvalidInputError(f"no shader files matched: {text}")
        for match in matches:
            if match not in seen:
                seen.add(match)
                expanded.append(match)
    return expanded
