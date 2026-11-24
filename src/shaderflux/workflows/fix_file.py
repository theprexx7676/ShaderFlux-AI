"""Fix one HLSL file: the workflow behind ``shaderflux fix``.

No AI, no network, no API key. The fixes are the mechanical ones from
:mod:`shaderflux.analysis.autofix`; the result is checked by linting the fixed text again.
"""

from __future__ import annotations

import difflib
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from shaderflux.analysis.autofix import FIXABLE_RULES, FixPlan, apply_edits, plan_fixes
from shaderflux.analysis.findings import Finding
from shaderflux.analysis.limits import exceeds_limits
from shaderflux.analysis.lint import lint_text
from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import ShaderLanguage
from shaderflux.pipeline.output import write_bytes_atomic
from shaderflux.source.includes import build_include_graph
from shaderflux.source.inputs import DEFAULT_MAX_BYTES, decode_text, detect_language

_BOM = b"\xef\xbb\xbf"


@dataclass
class FixRequest:
    input_file: Path
    rules: Collection[str] | None = None  # None: every fixable rule
    include_dirs: Sequence[Path] = ()
    write: bool = False  # change the input file in place
    out: Path | None = None  # or write the fixed copy here
    force: bool = False  # allow --out to replace an existing file


@dataclass
class FixOutcome:
    path: Path
    plan: FixPlan
    original: str
    fixed: str
    diff: str
    remaining: list[Finding] = field(default_factory=list)  # targeted findings still present
    notes: list[str] = field(default_factory=list)
    written_to: Path | None = None

    @property
    def changed(self) -> bool:
        return self.fixed != self.original

    @property
    def complete(self) -> bool:
        """True when every finding of the selected rules is gone."""
        return not self.remaining


def check_fix_request(request: FixRequest) -> None:
    """Reject bad option combinations and unwritable paths before touching anything."""
    if request.write and request.out is not None:
        raise InvalidInputError("use either --write or --out, not both")
    unknown = sorted(set(request.rules or ()) - set(FIXABLE_RULES))
    if unknown:
        raise InvalidInputError(
            f"cannot fix {', '.join(unknown)}; fixable rules: {', '.join(FIXABLE_RULES)}"
        )
    if request.out is not None:
        if request.out.is_dir():
            raise InvalidInputError(f"--out {request.out} is a directory; give a file name")
        if request.out.exists() and not request.force:
            raise InvalidInputError(f"{request.out} already exists (use --force to overwrite)")


def _selected(request: FixRequest) -> set[str]:
    return set(request.rules) if request.rules else set(FIXABLE_RULES)


def run_fix(request: FixRequest) -> FixOutcome:
    """Work out the fixes and, only if asked, write them. Never changes anything by default."""
    check_fix_request(request)
    path = Path(request.input_file)
    if not path.is_file():
        raise InvalidInputError(f"no such file: {path}")
    if (detect_language(path) or ShaderLanguage.HLSL) is not ShaderLanguage.HLSL:
        raise InvalidInputError(f"cannot fix {path.name}: only HLSL source is supported")
    if path.stat().st_size > DEFAULT_MAX_BYTES:
        raise InvalidInputError(f"{path} is over the {DEFAULT_MAX_BYTES} byte limit")

    raw = path.read_bytes()
    original = decode_text(raw, name=path.name)
    too_big = exceeds_limits(original)
    if too_big:
        raise InvalidInputError(f"{path.name} is too big to fix safely: {too_big}")
    rules = _selected(request)
    notes: list[str] = []

    graph = build_include_graph(path, request.include_dirs)
    if len(graph.files) > 1 and "BND001" in rules:
        # Bindings are decided across every file; fixing one file from its own view would be wrong.
        rules.discard("BND001")
        notes.append(
            "BND001 not fixed: this shader includes other files, and bindings are decided "
            "across all of them. Use the suggested -fvk-*-shift flags, or add [[vk::binding]] "
            "by hand (see 'shaderflux lint')."
        )

    plan = plan_fixes(original, rules=rules)
    fixed = apply_edits(original, plan.edits)
    notes += plan.skipped
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
        )
    )
    remaining = [f for f in lint_text(fixed, ShaderLanguage.HLSL) if f.rule in rules]

    outcome = FixOutcome(path, plan, original, fixed, diff, remaining, notes)
    target = path if request.write else request.out
    if target is not None and outcome.changed:
        data = fixed.encode("utf-8")
        write_bytes_atomic(target, (_BOM + data) if raw.startswith(_BOM) else data)
        outcome.written_to = target
    return outcome
