"""The LLM repair loop: fix compile errors with small, verified edits.

The model proposes edits; **the real compiler decides whether they worked**. A
patch is kept only if the tools accept the result or at least reduce the errors.
Nothing is written to disk here.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from enum import StrEnum

from shaderflux.core.errors import LlmError
from shaderflux.core.models import Diagnostic, Severity, ShaderSource, Target, TranslationResult
from shaderflux.llm.context import DEFAULT_BUDGET_CHARS, RepairPrompt, build_repair_prompt
from shaderflux.llm.patches import PatchError, apply_patch
from shaderflux.llm.prompts_loader import prompt_version
from shaderflux.llm.provider import LlmProvider, LlmRequest, UsageTotals
from shaderflux.llm.schemas import PATCH_SCHEMA, PatchProposal, parse_proposal
from shaderflux.pipeline.includes import build_include_graph
from shaderflux.pipeline.inputs import decode_text
from shaderflux.pipeline.translate import TranslateOptions, translate
from shaderflux.tools.base import BackendRegistry


class Outcome(StrEnum):
    FIXED = "fixed"
    IMPROVED = "improved"  # fewer or different errors; kept
    WORSE = "worse"  # more errors; patch discarded
    NO_CHANGE = "no_change"  # the model proposed nothing
    REJECTED = "rejected"  # invalid answer or unusable patch
    LLM_ERROR = "llm_error"


@dataclass
class Attempt:
    number: int
    outcome: Outcome
    message: str
    errors_before: int
    errors_after: int | None = None
    proposal: PatchProposal | None = None
    diff: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class RepairOptions:
    max_attempts: int = 3
    budget_chars: int = DEFAULT_BUDGET_CHARS
    max_total_tokens: int | None = 300_000
    allow_large_edits: bool = False
    effort: str = "high"
    translate: TranslateOptions | None = None


@dataclass
class RepairResult:
    ok: bool
    translation: TranslationResult
    source: ShaderSource  # the final source: patched if any patch was kept
    original_text: str
    attempts: list[Attempt] = field(default_factory=list)
    stop_reason: str = ""
    usage: UsageTotals = field(default_factory=UsageTotals)
    prompt_version: str = ""
    files_sent: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.source.text != self.original_text

    @property
    def diff(self) -> str:
        name = self.source.path.name if self.source.path else "shader"
        return "".join(
            difflib.unified_diff(
                self.original_text.splitlines(keepends=True),
                self.source.text.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )


def _errors(result: TranslationResult) -> list[Diagnostic]:
    return [d for d in result.diagnostics if d.severity is Severity.ERROR]


def _signature(errors: list[Diagnostic]) -> tuple[tuple[str, str], ...]:
    """Errors with line numbers removed, so a moved error still counts as the same one."""
    return tuple(sorted((d.severity.value, d.message) for d in errors))


def _context_files(source: ShaderSource, primary: str) -> dict[str, str]:
    """The shader plus the files in its include graph, and nothing else."""
    files = {primary: source.text}
    if source.path is not None and source.path.is_file():
        graph = build_include_graph(source.path, source.include_dirs)
        for path in graph.files:
            if path != graph.root:
                files[path.name] = decode_text(path.read_bytes(), name=path.name)
    return files


def prepare_repair_prompt(
    source: ShaderSource,
    target: Target,
    diagnostics: list[Diagnostic],
    *,
    tool: str = "unknown",
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> RepairPrompt:
    """Build the prompt without sending it (used by ``--dry-run``)."""
    primary = source.path.name if source.path else "shader"
    return build_repair_prompt(
        _context_files(source, primary),
        primary,
        diagnostics,
        source_language=source.language.value,
        target_language=target.language.value,
        tool=tool,
        budget_chars=budget_chars,
    )


def repair_and_translate(
    source: ShaderSource,
    target: Target,
    *,
    registry: BackendRegistry,
    provider: LlmProvider,
    options: RepairOptions | None = None,
) -> RepairResult:
    """Translate ``source``; if it fails to compile, ask the model for fixes and retry."""
    options = options or RepairOptions()
    original = source.text
    current = source
    translation = translate(current, target, registry=registry, options=options.translate)
    result = RepairResult(
        ok=translation.ok,
        translation=translation,
        source=current,
        original_text=original,
        prompt_version=prompt_version("system", "repair_compile_error"),
    )
    if translation.ok:
        result.stop_reason = "no repair needed"
        return result

    primary = source.path.name if source.path else "shader"
    seen = {_signature(_errors(translation))}

    for number in range(1, options.max_attempts + 1):
        errors = _errors(translation)
        failing = translation.stages[-1].name if translation.stages else ""
        if not failing.startswith("compile"):
            result.stop_reason = (
                f"the failure is in '{failing}', not a compile error; only compile errors "
                "can be repaired automatically"
            )
            break
        if (
            options.max_total_tokens is not None
            and result.usage.total_tokens >= options.max_total_tokens
        ):
            result.stop_reason = f"token budget reached ({result.usage.total_tokens} tokens)"
            break

        tool_name = translation.stages[-1].tool.name if translation.stages[-1].tool else "unknown"
        files = _context_files(current, primary)
        prompt = build_repair_prompt(
            files,
            primary,
            errors,
            source_language=current.language.value,
            target_language=target.language.value,
            tool=tool_name,
            budget_chars=options.budget_chars,
        )
        result.files_sent = prompt.files_sent
        request = LlmRequest(
            task="repair_compile_error",
            system=prompt.system,
            user=prompt.user,
            schema=PATCH_SCHEMA,
            effort=options.effort,
            prompt_version=result.prompt_version,
        )

        attempt = Attempt(
            number=number, outcome=Outcome.REJECTED, message="", errors_before=len(errors)
        )
        result.attempts.append(attempt)
        try:
            response = provider.complete(request)
        except LlmError as exc:
            attempt.outcome, attempt.message = Outcome.LLM_ERROR, str(exc)
            result.stop_reason = f"the model call failed: {exc}"
            break
        result.usage.add(response)
        attempt.input_tokens, attempt.output_tokens = response.input_tokens, response.output_tokens

        try:
            proposal = parse_proposal(response.text)
        except LlmError as exc:
            attempt.message = str(exc)
            continue
        attempt.proposal = proposal

        if not proposal.edits:
            attempt.outcome = Outcome.NO_CHANGE
            attempt.message = proposal.summary
            result.stop_reason = f"the model could not propose a fix: {proposal.summary}"
            break

        try:
            applied = apply_patch(
                files,
                proposal,
                editable=frozenset({primary}),
                allow_large=options.allow_large_edits,
            )
        except PatchError as exc:
            attempt.message = str(exc)
            continue
        attempt.diff = applied.diff

        candidate = current.model_copy(update={"text": applied.files[primary]})
        new_translation = translate(candidate, target, registry=registry, options=options.translate)
        new_errors = _errors(new_translation)
        attempt.errors_after = len(new_errors)

        if new_translation.ok:
            attempt.outcome, attempt.message = Outcome.FIXED, proposal.summary
            current, translation = candidate, new_translation
            result.ok, result.stop_reason = True, "fixed"
            break
        if len(new_errors) > len(errors):
            attempt.outcome = Outcome.WORSE
            attempt.message = f"{len(errors)} error(s) became {len(new_errors)}; patch discarded"
            continue

        signature = _signature(new_errors)
        current, translation = candidate, new_translation
        attempt.outcome = Outcome.IMPROVED
        attempt.message = proposal.summary
        if signature in seen:
            result.stop_reason = "no progress: the same errors came back"
            break
        seen.add(signature)
    else:
        result.stop_reason = f"gave up after {options.max_attempts} attempt(s)"

    if not result.stop_reason:
        result.stop_reason = f"gave up after {len(result.attempts)} attempt(s)"
    result.source = current
    result.translation = translation
    result.ok = translation.ok
    return result


def describe(result: RepairResult) -> str:
    """A short plain-text account of what happened, for the CLI and reports."""
    lines = [f"repair: {'fixed' if result.ok else 'not fixed'} ({result.stop_reason})"]
    for a in result.attempts:
        after = "" if a.errors_after is None else f" -> {a.errors_after}"
        lines.append(
            f"  attempt {a.number}: {a.outcome.value}, errors {a.errors_before}{after}: {a.message}"
        )
    lines.append(
        f"  tokens: {result.usage.input_tokens} in / {result.usage.output_tokens} out "
        f"over {result.usage.calls} call(s)"
    )
    return "\n".join(lines)


__all__ = [
    "Attempt",
    "Outcome",
    "RepairOptions",
    "RepairResult",
    "describe",
    "prepare_repair_prompt",
    "repair_and_translate",
]
