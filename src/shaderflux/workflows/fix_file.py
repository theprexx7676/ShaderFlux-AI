"""Fix one HLSL file: the workflow behind ``shaderflux fix``.

No AI, no network, no API key. The fixes are the mechanical ones from
:mod:`shaderflux.analysis.autofix`; the result is checked by linting the fixed text again.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from shaderflux.analysis.autofix import FIXABLE_RULES, FixPlan, apply_edits, plan_fixes
from shaderflux.analysis.findings import Finding
from shaderflux.analysis.limits import exceeds_limits
from shaderflux.analysis.lint import lint_text
from shaderflux.analysis.reflection import Reflection, reflect
from shaderflux.core.errors import InvalidInputError, ShaderFluxError, ToolMissingError
from shaderflux.core.models import Severity, ShaderLanguage, ShaderSource, ShaderStage, Target
from shaderflux.pipeline.output import write_bytes_atomic
from shaderflux.source.includes import build_include_graph
from shaderflux.source.inputs import DEFAULT_MAX_BYTES, decode_text, detect_language, detect_stage
from shaderflux.tools.registry import BackendRegistry, default_registry
from shaderflux.tools.spirv_cross import SpirvCrossBackend

_BOM = b"\xef\xbb\xbf"


@dataclass
class FixRequest:
    input_file: Path
    rules: Collection[str] | None = None  # None: every fixable rule
    include_dirs: Sequence[Path] = ()
    write: bool = False  # change the input file in place
    out: Path | None = None  # or write the fixed copy here
    force: bool = False  # allow --out to replace an existing file
    verify: bool = False  # recompile the fixed shader with a real compiler
    stage: ShaderStage | None = None  # for verify; default: detect
    entry_point: str = "main"
    tool_paths: Mapping[str, str] = field(default_factory=dict)


class VerifyStatus(StrEnum):
    OK = "ok"  # compiled, and no two resources share a binding
    NOT_RUN = "not-run"  # no compiler or stage: nothing was checked
    COLLISIONS = "collisions"  # compiled, but resources still share a binding
    STILL_BROKEN = "still-broken"  # does not compile, and did not before the fix either
    REGRESSED = "regressed"  # compiled before the fix, does not compile after it


@dataclass
class Verification:
    status: VerifyStatus
    detail: str
    tool: str | None = None


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
    verification: Verification | None = None

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


_SPIRV = Target(language=ShaderLanguage.SPIRV, environment="vulkan1.2")


def _default_reflect(tool_paths: Mapping[str, str]) -> Callable[[bytes], Reflection] | None:
    try:
        backend = SpirvCrossBackend.discover(configured=tool_paths)
    except ToolMissingError:
        return None
    return lambda spirv: reflect(spirv, backend)


def _verify(
    request: FixRequest,
    original: str,
    fixed: str,
    registry: BackendRegistry,
    reflector: Callable[[bytes], Reflection] | None,
) -> Verification:
    """Compile the fixed shader with a real compiler; say honestly what could not be checked."""
    path = request.input_file
    stage = request.stage or detect_stage(path, original, ShaderLanguage.HLSL)
    if stage is None:
        return Verification(
            VerifyStatus.NOT_RUN, "cannot tell the shader stage; pass --stage (e.g. fragment)"
        )
    try:
        compiler = registry.compiler_for(ShaderLanguage.HLSL)
    except ToolMissingError:
        return Verification(
            VerifyStatus.NOT_RUN, "no HLSL compiler found (install DXC; see 'shaderflux doctor')"
        )

    def build(text: str) -> ShaderSource:
        return ShaderSource(
            path=path,
            text=text,
            language=ShaderLanguage.HLSL,
            stage=stage,
            entry_point=request.entry_point,
            include_dirs=list(request.include_dirs),
        )

    after = compiler.compile(build(fixed), target=_SPIRV)
    name = f"{after.tool.name} {after.tool.version or ''}".strip()
    if not after.ok or after.output is None:
        errors = [d for d in after.diagnostics if d.severity is Severity.ERROR]
        first = errors[0].format() if errors else "compilation failed"
        before = compiler.compile(build(original), target=_SPIRV)
        if before.ok:
            return Verification(
                VerifyStatus.REGRESSED, f"compiled before the fix but not after: {first}", name
            )
        return Verification(
            VerifyStatus.STILL_BROKEN, f"does not compile, before or after the fix: {first}", name
        )
    if reflector is None:
        return Verification(
            VerifyStatus.OK,
            "compiled; bindings not checked (spirv-cross not found)",
            name,
        )
    try:
        slots = reflector(after.output).by_slot()
    except ShaderFluxError as exc:
        return Verification(
            VerifyStatus.OK, f"compiled; bindings not checked (reflection failed: {exc})", name
        )
    crowded = {slot: [r.name for r in found] for slot, found in slots.items() if len(found) > 1}
    if crowded:
        text = "; ".join(
            f"set {slot[0]} binding {slot[1]}: {', '.join(names)}"
            for slot, names in sorted(crowded.items())
        )
        return Verification(
            VerifyStatus.COLLISIONS, f"compiled, but bindings are shared: {text}", name
        )
    return Verification(VerifyStatus.OK, "compiled; every resource has its own binding", name)


def run_fix(
    request: FixRequest,
    *,
    registry: BackendRegistry | None = None,
    reflector: Callable[[bytes], Reflection] | None = None,
) -> FixOutcome:
    """Work out the fixes and, only if asked, write them. Never changes anything by default.

    ``registry`` and ``reflector`` can be injected (tests do); by default the installed tools
    are used, and only when ``verify`` is set.
    """
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
    if request.verify:
        try:
            outcome.verification = _verify(
                request,
                original,
                fixed,
                registry or default_registry(configured=request.tool_paths),
                reflector if reflector is not None else _default_reflect(request.tool_paths),
            )
        except ShaderFluxError as exc:
            outcome.verification = Verification(VerifyStatus.NOT_RUN, str(exc))
    target = path if request.write else request.out
    if outcome.verification and outcome.verification.status is VerifyStatus.REGRESSED:
        notes.append("not written: the fix made a shader that compiled stop compiling")
    elif target is not None and outcome.changed:
        data = fixed.encode("utf-8")
        write_bytes_atomic(target, (_BOM + data) if raw.startswith(_BOM) else data)
        outcome.written_to = target
    return outcome
