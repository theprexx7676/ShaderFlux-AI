"""HLSL register to Vulkan descriptor binding analysis.

Why this matters: HLSL numbers resources per register *type* (``b0``, ``t0``,
``s0`` and ``u0`` are four different slots), while Vulkan has one binding number
space per descriptor set. DXC, by default, maps ``register(xN, spaceM)`` to
``set=M, binding=N`` **ignoring the register type** (DXC's SPIR-V documentation
says so; plan task 4.2.4 still has to confirm it against a real ``dxc``). So a
perfectly valid HLSL shader with ``b0`` and ``t0`` produces two resources on the
same Vulkan binding.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.core.models import Severity
from shaderflux.core.text import LineIndex
from shaderflux.pipeline.includes import mask_comments
from shaderflux.tools.dxc import BindingPolicy

RegType = Literal["b", "t", "s", "u"]
_TYPE_ORDER: tuple[RegType, ...] = ("b", "t", "s", "u")

_REGISTER = re.compile(
    r"(?<!\w)(?P<name>\w+)(?:\s*\[[^\]]*\])?\s*:\s*register\s*\(\s*"
    r"(?P<type>[btsu])(?P<num>\d+)\s*(?:,\s*space(?P<space>\d+)\s*)?\)"
)
_VK_BINDING = re.compile(
    r"\[\[\s*vk::binding\s*\(\s*(?P<binding>\d+)\s*(?:,\s*(?P<set>\d+)\s*)?\)\s*\]\]"
)
_TRAILING_REGISTER = re.compile(r":\s*register\s*\([^)]*\)$")
_TRAILING_ARRAY = re.compile(r"\[[^\]]*\]$")
_MAX_DECLARATION_CHARS = 2000


def _declared_name(declaration: str) -> str | None:
    """The identifier a declaration declares, found by walking back from its end.

    Done by hand rather than with one big regex: the regex version backtracked
    quadratically on long runs of whitespace (a denial-of-service on hostile input).
    """
    text = declaration.strip()
    if len(text) > _MAX_DECLARATION_CHARS:
        return None
    text = _TRAILING_REGISTER.sub("", text).rstrip()
    text = _TRAILING_ARRAY.sub("", text).rstrip()
    end = len(text)
    start = end
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    return text[start:end] if start < end else None


class HlslBinding(BaseModel):
    """One resource declaration with its register and/or Vulkan attribute."""

    name: str
    file: str | None = None
    reg_type: RegType | None = None
    number: int | None = None
    space: int = 0
    line: int = 1
    vk_binding: int | None = None
    vk_set: int | None = None

    @property
    def has_vk_attribute(self) -> bool:
        return self.vk_binding is not None

    @property
    def register(self) -> str:
        if self.reg_type is None:
            return "(no register)"
        text = f"{self.reg_type}{self.number}"
        return text + (f", space{self.space}" if self.space else "")

    def default_slot(self) -> tuple[int, int] | None:
        """``(set, binding)`` DXC picks with no binding flags."""
        if self.vk_binding is not None:
            return (self.vk_set or 0, self.vk_binding)
        if self.number is not None:
            return (self.space, self.number)
        return None


class Collision(BaseModel):
    slot: tuple[int, int]
    file: str | None = None
    names: list[str]
    registers: list[str]
    line: int


class BindingPlan(BaseModel):
    bindings: list[HlslBinding] = Field(default_factory=list)
    collisions: list[Collision] = Field(default_factory=list)
    policy: BindingPolicy | None = None
    unresolved: list[Collision] = Field(default_factory=list)


def parse_hlsl_bindings(text: str, *, file: str | None = None) -> list[HlslBinding]:
    """Find every ``register(...)`` and ``[[vk::binding(...)]]`` in HLSL source.

    Conservative: anything not recognised is skipped, never guessed.
    """
    masked = mask_comments(text)
    found: dict[str, HlslBinding] = {}

    index = LineIndex(masked)

    def line_of(pos: int) -> int:
        return index.line_of(pos)

    for match in _REGISTER.finditer(masked):
        name = match.group("name")
        found[name] = HlslBinding(
            name=name,
            file=file,
            reg_type=match.group("type"),
            number=int(match.group("num")),
            space=int(match.group("space") or 0),
            line=line_of(match.start()),
        )

    for match in _VK_BINDING.finditer(masked):
        segment_end = min(
            (i for i in (masked.find(";", match.end()), masked.find("{", match.end())) if i != -1),
            default=len(masked),
        )
        declaration = masked[match.end() : segment_end]
        name = _declared_name(declaration)
        if name is None:
            continue
        binding = int(match.group("binding"))
        vk_set = int(match.group("set")) if match.group("set") is not None else None
        entry = found.get(name)
        if entry is None:
            entry = HlslBinding(name=name, file=file, line=line_of(match.start()))
            found[name] = entry
        entry.vk_binding = binding
        entry.vk_set = vk_set

    return sorted(found.values(), key=lambda b: (b.line, b.name))


def find_collisions(
    bindings: Sequence[HlslBinding], *, shifts: Mapping[RegType, int] | None = None
) -> list[Collision]:
    """Resources that end up on the same ``(set, binding)``.

    ``shifts`` models DXC's ``-fvk-<type>-shift`` options (applied to every space).
    ``[[vk::binding]]`` attributes win over shifts, as in DXC.
    """
    shifts = shifts or {}
    slots: dict[tuple[int, int], list[HlslBinding]] = {}
    for binding in bindings:
        if binding.has_vk_attribute:
            slot = binding.default_slot()
        elif binding.number is not None and binding.reg_type is not None:
            slot = (binding.space, binding.number + shifts.get(binding.reg_type, 0))
        else:
            slot = None
        if slot is not None:
            slots.setdefault(slot, []).append(binding)

    collisions: list[Collision] = []
    for slot, group in sorted(slots.items()):
        if len(group) > 1:
            collisions.append(
                Collision(
                    slot=slot,
                    file=min(group, key=lambda g: g.line).file,
                    names=[g.name for g in group],
                    registers=[g.register for g in group],
                    line=min(g.line for g in group),
                )
            )
    return collisions


def propose_policy(bindings: Sequence[HlslBinding]) -> BindingPlan:
    """Work out collisions and, if any, a ``-fvk-*-shift`` policy that removes them.

    Each register type gets its own binding range, so ranges never overlap in any
    space. The result is checked with :func:`find_collisions` before it is
    returned; anything that still collides (for example two ``[[vk::binding]]``
    attributes on the same slot) is reported in ``unresolved``.
    """
    plan = BindingPlan(bindings=list(bindings), collisions=find_collisions(bindings))
    if not plan.collisions:
        return plan

    register_mapped = [
        b for b in bindings if b.reg_type and b.number is not None and not b.has_vk_attribute
    ]
    offset = 0
    shifts: dict[RegType, int] = {}
    for reg_type in _TYPE_ORDER:
        numbers = [
            b.number for b in register_mapped if b.reg_type == reg_type and b.number is not None
        ]
        if not numbers:
            continue
        if offset:
            shifts[reg_type] = offset
        offset += max(numbers) + 1

    policy = BindingPolicy(shifts=shifts)
    plan.policy = policy
    plan.unresolved = find_collisions(bindings, shifts=shifts)
    return plan


def binding_findings(plan: BindingPlan, *, file: str | None = None) -> list[Finding]:
    """Turn a plan into lint findings."""
    findings: list[Finding] = []
    for collision in plan.collisions:
        names = ", ".join(
            f"{n} ({r})" for n, r in zip(collision.names, collision.registers, strict=True)
        )
        resolved = plan.policy is not None and collision not in plan.unresolved
        suggestion = None
        if plan.policy is not None and plan.policy.shifts:
            flags = " ".join(plan.policy.to_args())
            suggestion = f"compile with {flags} (or use [[vk::binding]] attributes)"
        findings.append(
            Finding(
                rule="BND001",
                severity=Severity.ERROR,
                message=(
                    f"{names} all map to Vulkan set {collision.slot[0]}, binding "
                    f"{collision.slot[1]}: DXC ignores the register type by default"
                ),
                file=collision.file or file,
                line=collision.line,
                confidence=Confidence.HIGH,
                suggestion=suggestion
                if resolved
                else "use [[vk::binding]] attributes to separate them",
            )
        )
    for leftover in plan.unresolved:
        findings.append(
            Finding(
                rule="BND002",
                severity=Severity.ERROR,
                message=(
                    f"{', '.join(leftover.names)} still share set {leftover.slot[0]}, binding "
                    f"{leftover.slot[1]} even with shifts (explicit [[vk::binding]] clash)"
                ),
                file=leftover.file or file,
                line=leftover.line,
                confidence=Confidence.HIGH,
                suggestion="give each [[vk::binding]] a distinct (binding, set)",
            )
        )
    return findings
