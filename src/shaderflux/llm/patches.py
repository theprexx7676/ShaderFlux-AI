"""Applying model-proposed edits safely.

The model never writes files. It proposes line-range replacements with the text
it expects to replace. An edit is rejected when that text no longer matches (the
model misread the file), when it targets a file we did not offer, when edits
overlap, or when the change is suspiciously large.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass

from shaderflux.core.errors import LlmError
from shaderflux.llm.schemas import Edit, PatchProposal

DEFAULT_MAX_CHANGE_FRACTION = 0.5
MIN_ALLOWED_CHANGED_LINES = 20


class PatchError(LlmError):
    """The proposed edit cannot be applied."""


@dataclass(frozen=True)
class AppliedPatch:
    files: dict[str, str]
    diff: str
    changed_lines: int


def _split(text: str) -> tuple[list[str], bool, str]:
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split("\n")
    trailing = lines[-1] == ""
    if trailing:
        lines.pop()
    return [line.removesuffix("\r") for line in lines], trailing, newline


def _join(lines: list[str], trailing: bool, newline: str) -> str:
    return newline.join(lines) + (newline if trailing and lines else "")


def _normalise(text: str) -> str:
    return "\n".join(part.removesuffix("\r") for part in text.strip("\r\n").split("\n"))


def apply_patch(
    files: Mapping[str, str],
    proposal: PatchProposal,
    *,
    editable: frozenset[str] | None = None,
    allow_large: bool = False,
    max_change_fraction: float = DEFAULT_MAX_CHANGE_FRACTION,
) -> AppliedPatch:
    """Apply ``proposal`` to a copy of ``files``.

    ``editable`` limits which files may change (default: all given files).
    Raises :class:`PatchError` and changes nothing if any edit is invalid.
    """
    if not proposal.edits:
        raise PatchError("the proposal contains no edits")
    allowed = editable if editable is not None else frozenset(files)

    by_file: dict[str, list[Edit]] = {}
    for edit in proposal.edits:
        if edit.file not in files:
            raise PatchError(f"edit targets a file that was not provided: {edit.file!r}")
        if edit.file not in allowed:
            raise PatchError(f"{edit.file!r} is read-only context and cannot be edited")
        by_file.setdefault(edit.file, []).append(edit)

    result = dict(files)
    changed = 0
    for name, edits in by_file.items():
        lines, trailing, newline = _split(files[name])
        ordered = sorted(edits, key=lambda e: e.start_line)
        previous_end = 0
        for edit in ordered:
            if edit.end_line < edit.start_line:
                raise PatchError(f"{name}: end_line {edit.end_line} is before start_line")
            if edit.end_line > len(lines):
                raise PatchError(
                    f"{name}: line {edit.end_line} is past the end ({len(lines)} lines)"
                )
            if edit.start_line <= previous_end:
                raise PatchError(f"{name}: edits overlap around line {edit.start_line}")
            previous_end = edit.end_line
            actual = "\n".join(lines[edit.start_line - 1 : edit.end_line])
            if _normalise(edit.expected) != _normalise(actual):
                raise PatchError(
                    f"{name}: lines {edit.start_line}-{edit.end_line} do not match what the "
                    "model expected (stale or misread edit)"
                )

        for edit in reversed(ordered):
            replacement = edit.replacement.strip("\r\n")
            new_lines = replacement.split("\n") if replacement != "" else []
            changed += max(edit.end_line - edit.start_line + 1, len(new_lines))
            lines[edit.start_line - 1 : edit.end_line] = [x.removesuffix("\r") for x in new_lines]

        limit = max(MIN_ALLOWED_CHANGED_LINES, int(max_change_fraction * max(len(lines), 1)))
        if changed > limit and not allow_large:
            raise PatchError(
                f"{name}: the edit touches {changed} lines, over the limit of {limit} "
                "(pass --allow-large-edits to accept bigger rewrites)"
            )
        result[name] = _join(lines, trailing, newline)

    diff = "".join(
        "".join(
            difflib.unified_diff(
                files[name].splitlines(keepends=True),
                result[name].splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )
        for name in by_file
    )
    return AppliedPatch(files=result, diff=diff, changed_lines=changed)
