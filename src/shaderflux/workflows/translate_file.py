"""Translate one shader file: the workflow behind ``shaderflux translate``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from shaderflux.analysis.findings import Finding
from shaderflux.analysis.lint import lint_file
from shaderflux.core.errors import InvalidInputError, ShaderFluxError
from shaderflux.core.models import (
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    Target,
    TranslationResult,
)
from shaderflux.llm.anthropic_provider import INSTALL_HINT, AnthropicProvider, sdk_available
from shaderflux.llm.prompts_loader import prompt_version
from shaderflux.llm.provider import DEFAULT_MODEL, LlmProvider, LlmRequest
from shaderflux.llm.repair import (
    Outcome,
    RepairOptions,
    RepairResult,
    prepare_repair_prompt,
    repair_and_translate,
    repair_blocker,
)
from shaderflux.llm.schemas import PATCH_SCHEMA
from shaderflux.pipeline.cache import TranslationCache
from shaderflux.pipeline.output import write_output
from shaderflux.pipeline.translate import TranslateOptions, translate
from shaderflux.reporting.report import build_report, write_report
from shaderflux.source.inputs import load_source
from shaderflux.tools.base import CrossOptions
from shaderflux.tools.registry import BackendRegistry, default_registry


@dataclass
class TranslateRequest:
    """Everything needed to translate one file. Defaults match the command line."""

    input_file: Path
    target_language: ShaderLanguage
    target_version: str | None = None
    environment: str = "vulkan1.2"
    source_language: ShaderLanguage | None = None
    stage: ShaderStage | None = None
    entry_point: str | None = None
    defines: Mapping[str, str | None] = field(default_factory=dict)
    include_dirs: Sequence[Path] = ()
    tool_paths: Mapping[str, str] = field(default_factory=dict)

    roundtrip: bool = False
    validate: bool = True
    recheck: bool = True
    vulkan_semantics: bool = False
    cache_dir: Path | None = None  # None: no cache

    out: Path | None = None
    force: bool = False
    report: Path | None = None

    # AI-assisted repair (off by default)
    repair: bool = False
    dry_run: bool = False
    max_attempts: int = 3
    allow_large_edits: bool = False
    write_fixed: Path | None = None
    model: str | None = None


@dataclass
class DryRun:
    """What *would* be sent to the model. Nothing has been sent."""

    request: LlmRequest
    files_sent: list[str]
    notes: list[str]


@dataclass
class TranslateOutcome:
    source: ShaderSource
    target: Target
    result: TranslationResult
    repair: RepairResult | None = None
    dry_run: DryRun | None = None
    nothing_to_repair: bool = False
    not_repairable: str | None = None  # dry run: why nothing would be sent
    report_path: Path | None = None
    fixed_path: Path | None = None

    @property
    def model_call_failed(self) -> bool:
        """True when the translation failed *and* the reason was a failed model call."""
        return (
            not self.result.ok
            and self.repair is not None
            and any(a.outcome is Outcome.LLM_ERROR for a in self.repair.attempts)
        )


def check_request(request: TranslateRequest, *, needs_sdk: bool = True) -> None:
    """Reject conflicting options and unwritable output paths *before* any work or LLM spend.

    ``needs_sdk`` is false when the caller supplies its own model provider (tests do).
    """
    if request.repair and not request.dry_run and needs_sdk and not sdk_available():
        raise InvalidInputError(INSTALL_HINT)
    if request.dry_run and not request.repair:
        raise InvalidInputError("dry_run only makes sense together with repair")
    if request.write_fixed is not None and not request.repair:
        raise InvalidInputError("write_fixed only makes sense together with repair")
    for flag, path in (("--out", request.out), ("--write-fixed", request.write_fixed)):
        if path is None:
            continue
        if path.is_dir():
            raise InvalidInputError(f"{flag} {path} is a directory; give a file name")
        if path.exists() and not request.force:
            raise InvalidInputError(f"{path} already exists (use --force to overwrite)")
    if request.report is not None and request.report.is_dir():
        raise InvalidInputError(f"--report {request.report} is a directory; give a file name")


def _porting_risks(source: ShaderSource) -> list[Finding] | None:
    if source.path is None or source.language not in (ShaderLanguage.HLSL, ShaderLanguage.GLSL):
        return None
    try:
        return lint_file(
            source.path, language=source.language, include_dirs=source.include_dirs
        ).findings
    except ShaderFluxError:
        return None


def _dry_run(source: ShaderSource, target: Target, result: TranslationResult) -> DryRun:
    errors = [d for d in result.diagnostics if d.severity is Severity.ERROR]
    tool = result.stages[-1].tool.name if result.stages and result.stages[-1].tool else "unknown"
    prompt = prepare_repair_prompt(source, target, errors, tool=tool)
    return DryRun(
        request=LlmRequest(
            task="repair_compile_error",
            system=prompt.system,
            user=prompt.user,
            schema=PATCH_SCHEMA,
            prompt_version=prompt_version("system", "repair_compile_error"),
        ),
        files_sent=prompt.files_sent,
        notes=prompt.notes,
    )


def run_translate(
    request: TranslateRequest,
    *,
    registry: BackendRegistry | None = None,
    provider: LlmProvider | None = None,
) -> TranslateOutcome:
    """Run the whole translate workflow and return what happened.

    ``registry`` and ``provider`` can be injected (tests do); by default the tools found
    on this machine and the Anthropic API are used.
    """
    check_request(request, needs_sdk=provider is None)
    source = load_source(
        request.input_file,
        language=request.source_language,
        stage=request.stage,
        entry_point=request.entry_point,
        defines=request.defines,
        include_dirs=request.include_dirs,
    )
    target = Target(
        language=request.target_language,
        version=request.target_version,
        environment=request.environment,
    )
    options = TranslateOptions(
        roundtrip=request.roundtrip,
        validate=request.validate,
        recheck=request.recheck,
        cross=CrossOptions(vulkan_semantics=request.vulkan_semantics),
        cache=TranslationCache(request.cache_dir) if request.cache_dir else None,
    )
    registry = registry or default_registry(configured=request.tool_paths)

    repair: RepairResult | None = None
    if request.repair and request.dry_run:
        result = translate(source, target, registry=registry, options=options)
        if result.ok:
            return TranslateOutcome(source, target, result, nothing_to_repair=True)
        blocker = repair_blocker(result)
        if blocker is not None:
            return TranslateOutcome(source, target, result, not_repairable=blocker)
        return TranslateOutcome(source, target, result, dry_run=_dry_run(source, target, result))

    if request.repair:
        provider = provider or AnthropicProvider(model=request.model or DEFAULT_MODEL)
        repair = repair_and_translate(
            source,
            target,
            registry=registry,
            provider=provider,
            options=RepairOptions(
                max_attempts=request.max_attempts,
                allow_large_edits=request.allow_large_edits,
                translate=options,
            ),
        )
        result = repair.translation
    else:
        result = translate(source, target, registry=registry, options=options)

    outcome = TranslateOutcome(source, target, result, repair=repair)
    if request.out is not None and result.ok:
        result.output_path = write_output(result, request.out, force=request.force)
    if request.report is not None:
        outcome.report_path = write_report(
            build_report(source, target, result, repair=repair, findings=_porting_risks(source)),
            request.report,
        )
    if request.write_fixed is not None and repair is not None and repair.ok and repair.changed:
        fixed = TranslationResult(ok=True, output_text=repair.source.text)
        outcome.fixed_path = write_output(fixed, request.write_fixed, force=request.force)
    return outcome
