"""Deterministic fixes for lint findings: no AI, no network, no key.

Only fixes that are mechanical and behaviour-preserving are offered:

* ``BND001`` (colliding Vulkan bindings): insert ``[[vk::binding(binding, set)]]`` before each
  resource that the proposed ``-fvk-*-shift`` flags would move. This gives the same bindings
  as the flags, but lives in the source; D3D builds keep using the ``register(...)``.
* ``MAT002`` (matrix without an explicit layout): insert ``column_major``, which is what DXC
  already does for an unqualified matrix, so nothing changes except that it is now stated.

Every fix is an insertion, so applying them never deletes or rewrites existing code.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field

from shaderflux.analysis.bindings import HlslBinding, parse_hlsl_bindings, propose_policy
from shaderflux.analysis.matrix_rules import unqualified_buffer_matrices
from shaderflux.core.text import LineIndex
from shaderflux.source.includes import mask_comments

FIXABLE_RULES = ("BND001", "MAT002")
_MAX_STATEMENT_CHARS = 2000  # a longer "declaration" is not one; also keeps scanning linear
_REGISTER_WORD = re.compile(r"\bregister\s*\(")


@dataclass(frozen=True)
class TextEdit:
    """Insert ``text`` at character ``offset``."""

    offset: int
    text: str
    rule: str
    line: int
    description: str


@dataclass
class FixPlan:
    edits: list[TextEdit] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # reasons a finding was left alone

    @property
    def rules(self) -> set[str]:
        return {edit.rule for edit in self.edits}


def _statement_start(masked: str, pos: int) -> int | None:
    """Offset of the first token of the declaration that contains ``pos`` (comments are masked)."""
    start = pos
    limit = max(0, pos - _MAX_STATEMENT_CHARS)
    while start > limit and masked[start - 1] not in ";{}":
        start -= 1
    if start == limit and start > 0 and masked[start - 1] not in ";{}":
        return None  # no statement boundary nearby
    while start < pos:
        if masked[start].isspace():
            start += 1
        elif masked[start] == "#":  # a preprocessor line before the declaration
            end = masked.find("\n", start)
            if end == -1:
                return None
            start = end + 1
        else:
            break
    return start if start < pos else None


def _single_declaration(masked: str, start: int) -> bool:
    """True when the statement from ``start`` declares exactly one registered resource."""
    ends = [i for i in (masked.find(";", start), masked.find("{", start)) if i != -1]
    end = min(ends, default=len(masked))
    return len(_REGISTER_WORD.findall(masked[start : min(end, start + _MAX_STATEMENT_CHARS)])) == 1


def _binding_edits(text: str, masked: str, lines: LineIndex, plan: FixPlan) -> None:
    bindings = parse_hlsl_bindings(text)
    result = propose_policy(bindings)
    if not result.collisions:
        return
    if result.unresolved or result.policy is None:
        plan.skipped.append(
            "BND001: two [[vk::binding]] attributes clash; give them distinct slots by hand"
        )
        return
    shifts = result.policy.shifts
    for binding in bindings:
        if binding.reg_type is None or binding.number is None or binding.has_vk_attribute:
            continue
        shift = shifts.get(binding.reg_type, 0)
        if shift == 0:
            continue  # the register already maps to the right binding
        edit = _binding_edit(binding, shift, masked, lines, plan)
        if edit is not None:
            plan.edits.append(edit)


def _binding_edit(
    binding: HlslBinding, shift: int, masked: str, lines: LineIndex, plan: FixPlan
) -> TextEdit | None:
    start = _statement_start(masked, binding.offset)
    if start is None or not _single_declaration(masked, start):
        plan.skipped.append(
            f"BND001: could not place an attribute safely before '{binding.name}' "
            f"(line {binding.line}); add [[vk::binding]] by hand"
        )
        return None
    assert binding.number is not None
    slot = binding.number + shift
    return TextEdit(
        offset=start,
        text=f"[[vk::binding({slot}, {binding.space})]] ",
        rule="BND001",
        line=lines.line_of(start),
        description=(
            f"{binding.name} ({binding.register}) -> Vulkan binding {slot}, set {binding.space}"
        ),
    )


def plan_fixes(text: str, *, rules: Collection[str] | None = None) -> FixPlan:
    """Work out the fixes for HLSL source. Nothing is changed; apply with :func:`apply_edits`."""
    wanted = set(rules) if rules is not None else set(FIXABLE_RULES)
    plan = FixPlan()
    masked = mask_comments(text)
    lines = LineIndex(masked)
    if "BND001" in wanted:
        _binding_edits(text, masked, lines, plan)
    if "MAT002" in wanted:
        for site in unqualified_buffer_matrices(text):
            plan.edits.append(
                TextEdit(
                    offset=site.offset,
                    text="column_major ",
                    rule="MAT002",
                    line=site.line,
                    description=(
                        f"matrix '{site.name}': state column_major, which is what DXC already does"
                    ),
                )
            )
    plan.edits.sort(key=lambda e: (e.offset, e.rule))
    return plan


def apply_edits(text: str, edits: Collection[TextEdit]) -> str:
    """Insert every edit. Pure insertion: the original text is preserved around them."""
    pieces: list[str] = []
    cursor = 0
    for edit in sorted(edits, key=lambda e: e.offset):
        pieces.append(text[cursor : edit.offset])
        pieces.append(edit.text)
        cursor = edit.offset
    pieces.append(text[cursor:])
    return "".join(pieces)
