"""Building the smallest sufficient prompt for a repair.

Privacy rule (plan 5.6.4): only files the caller passes in are ever included, and
the caller passes only the shader and the files in its ``#include`` graph. Nothing
else from the machine (environment variables, absolute paths, other files) reaches
the model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from shaderflux.core.models import Diagnostic
from shaderflux.llm.prompts_loader import load_prompt

DEFAULT_BUDGET_CHARS = 60_000  # roughly 15k tokens
WINDOW_LINES = 60


@dataclass(frozen=True)
class RepairPrompt:
    system: str
    user: str
    files_sent: list[str]
    notes: list[str] = field(default_factory=list)


def numbered(text: str, first_line: int = 1) -> str:
    return "\n".join(f"{i:>5}| {line}" for i, line in enumerate(text.split("\n"), first_line))


def _window(text: str, centres: Sequence[int]) -> tuple[str, int, int]:
    lines = text.split("\n")
    low = max(1, min(centres) - WINDOW_LINES) if centres else 1
    high = min(len(lines), max(centres) + WINDOW_LINES) if centres else len(lines)
    return "\n".join(lines[low - 1 : high]), low, high


def _block(name: str, text: str, *, editable: bool, first_line: int = 1, note: str = "") -> str:
    kind = "editable" if editable else "read-only context"
    header = f'<shader_source file="{name}" mode="{kind}"{note}>'
    return f"{header}\n{numbered(text, first_line)}\n</shader_source>"


def build_repair_prompt(
    files: Mapping[str, str],
    primary: str,
    diagnostics: Sequence[Diagnostic],
    *,
    source_language: str,
    target_language: str,
    tool: str,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> RepairPrompt:
    """Assemble the system and user prompt for fixing ``primary``."""
    notes: list[str] = []
    text = files[primary]
    diag_text = "\n".join(d.format() for d in diagnostics) or "(no diagnostics)"

    blocks: list[str] = []
    sent: list[str] = []

    primary_block = _block(primary, text, editable=True)
    if len(primary_block) > budget_chars:
        centres = [d.line for d in diagnostics if d.line is not None]
        snippet, low, high = _window(text, centres)
        primary_block = _block(
            primary,
            snippet,
            editable=True,
            first_line=low,
            note=f' lines="{low}-{high}"',
        )
        notes.append(f"{primary}: only lines {low}-{high} were sent (over the size budget)")
    blocks.append(primary_block)
    sent.append(primary)

    used = len(primary_block) + len(diag_text)
    for name, content in files.items():
        if name == primary:
            continue
        block = _block(name, content, editable=False)
        if used + len(block) > budget_chars:
            notes.append(f"{name}: left out (over the size budget)")
            continue
        blocks.append(block)
        sent.append(name)
        used += len(block)

    user = load_prompt("repair_compile_error").render(
        source_language=source_language,
        target_language=target_language,
        tool=tool,
        diagnostics=diag_text,
        files="\n\n".join(blocks),
        editable=primary,
    )
    return RepairPrompt(system=load_prompt("system").body, user=user, files_sent=sent, notes=notes)
