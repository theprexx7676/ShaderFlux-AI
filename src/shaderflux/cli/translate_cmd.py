"""``shaderflux translate``."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import typer

from shaderflux.analysis.lint import lint_file
from shaderflux.cli.errors import EXIT_FAILED, EXIT_OK, EXIT_TOOL, eprint, handle_errors
from shaderflux.core.config import load_settings
from shaderflux.core.errors import InvalidInputError, ShaderFluxError
from shaderflux.core.logging import setup_logging
from shaderflux.core.models import Severity, ShaderLanguage, Target, TranslationResult
from shaderflux.llm.anthropic_provider import AnthropicProvider
from shaderflux.llm.prompts_loader import prompt_version
from shaderflux.llm.provider import DEFAULT_MODEL, LlmRequest
from shaderflux.llm.repair import (
    Outcome,
    RepairOptions,
    RepairResult,
    describe,
    prepare_repair_prompt,
    repair_and_translate,
)
from shaderflux.llm.schemas import PATCH_SCHEMA
from shaderflux.pipeline.cache import TranslationCache
from shaderflux.pipeline.inputs import load_source, parse_language_name, parse_stage_name
from shaderflux.pipeline.output import write_output
from shaderflux.pipeline.translate import TranslateOptions, translate
from shaderflux.reporting.report import build_report, write_report
from shaderflux.tools.base import CrossOptions
from shaderflux.tools.registry import default_registry


def parse_define(raw: str) -> tuple[str, str | None]:
    """``NAME`` or ``NAME=VALUE``."""
    name, sep, value = raw.partition("=")
    if not name:
        raise InvalidInputError(f"invalid define {raw!r}; use NAME or NAME=VALUE")
    return name, (value if sep else None)


def _preflight(
    *,
    repair: bool,
    dry_run: bool,
    write_fixed: Path | None,
    allow_large_edits: bool,
    max_attempts: int | None,
    out: Path | None,
    force: bool,
    report: Path | None,
) -> None:
    """Reject bad option combinations and unwritable outputs *before* any work or LLM spend."""
    if not repair:
        stray = [
            flag
            for flag, given in (
                ("--dry-run", dry_run),
                ("--write-fixed", write_fixed is not None),
                ("--allow-large-edits", allow_large_edits),
                ("--max-attempts", max_attempts is not None),
            )
            if given
        ]
        if stray:
            raise InvalidInputError(f"{', '.join(stray)} only make sense together with --repair")
    for flag, path in (("--out", out), ("--write-fixed", write_fixed)):
        if path is None:
            continue
        if path.is_dir():
            raise InvalidInputError(f"{flag} {path} is a directory; give a file name")
        if path.exists() and not force:
            raise InvalidInputError(f"{path} already exists (use --force to overwrite)")
    if report is not None and report.is_dir():
        raise InvalidInputError(f"--report {report} is a directory; give a file name")


@handle_errors
def translate_command(
    input_file: Path = typer.Argument(..., help="Shader file to translate.", exists=False),
    to: str = typer.Option(..., "--to", "-t", help="Target: glsl, hlsl, spirv or msl."),
    from_: str | None = typer.Option(None, "--from", help="Source language (default: detect)."),
    stage: str | None = typer.Option(None, "--stage", "-s", help="vertex, fragment, compute, ..."),
    entry: str | None = typer.Option(None, "--entry", "-e", help="Entry point (default: main)."),
    define: list[str] = typer.Option([], "-D", help="Preprocessor define, NAME or NAME=VALUE."),
    include: list[Path] = typer.Option([], "-I", help="Include directory (repeatable)."),
    out: Path | None = typer.Option(None, "--out", "-o", help="Write the result to this file."),
    force: bool = typer.Option(False, "--force", help="Overwrite --out if it exists."),
    glsl_version: str | None = typer.Option(None, "--glsl-version", help="For glsl, e.g. 450."),
    shader_model: str | None = typer.Option(None, "--hlsl-model", help="For hlsl, e.g. 50 or 60."),
    msl_version: str | None = typer.Option(None, "--msl-version", help="For msl, e.g. 20100."),
    vulkan: bool = typer.Option(False, "--vulkan", help="Emit Vulkan-style GLSL."),
    environment: str | None = typer.Option(None, "--env", help="SPIR-V env, e.g. vulkan1.2."),
    roundtrip: bool = typer.Option(False, "--roundtrip", help="Allow same-language conversion."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Run spirv-val."),
    recheck: bool = typer.Option(
        True, "--recheck/--no-recheck", help="Compile the generated GLSL/HLSL again to confirm it."
    ),
    cache: bool = typer.Option(False, "--cache", help="Reuse results of identical runs."),
    json_output: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    repair: bool = typer.Option(
        False, "--repair", help="If it fails to compile, ask Claude for fixes (sends your shader)."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="With --repair: show exactly what would be sent; send nothing."
    ),
    max_attempts: int | None = typer.Option(
        None, "--max-attempts", min=1, max=10, help="Repair attempts (1 to 10)."
    ),
    allow_large_edits: bool = typer.Option(
        False, "--allow-large-edits", help="Accept big rewrites."
    ),
    report: Path | None = typer.Option(
        None, "--report", help="Write a report of this run (.md for Markdown, otherwise JSON)."
    ),
    write_fixed: Path | None = typer.Option(
        None, "--write-fixed", help="With --repair: save the corrected source to this file."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Translate a shader to another language using the deterministic tool chain."""
    setup_logging(verbose=verbose, quiet=quiet)
    _preflight(
        repair=repair,
        dry_run=dry_run,
        write_fixed=write_fixed,
        allow_large_edits=allow_large_edits,
        max_attempts=max_attempts,
        out=out,
        force=force,
        report=report,
    )
    settings = load_settings().settings

    target_language = parse_language_name(to)
    version = {
        ShaderLanguage.GLSL: glsl_version,
        ShaderLanguage.HLSL: shader_model,
        ShaderLanguage.MSL: msl_version,
    }.get(target_language)
    target = Target(
        language=target_language,
        version=version,
        environment=environment or settings.default_environment,
    )

    defines = dict(parse_define(item) for item in define)
    source = load_source(
        input_file,
        language=parse_language_name(from_) if from_ else None,
        stage=parse_stage_name(stage) if stage else None,
        entry_point=entry,
        defines=defines,
        include_dirs=[*settings.include_dirs, *include],
    )

    cache_dir = settings.cache_dir or Path(platformdirs.user_cache_dir("shaderflux"))
    options = TranslateOptions(
        roundtrip=roundtrip,
        validate=validate,
        recheck=recheck,
        cross=CrossOptions(vulkan_semantics=vulkan),
        cache=TranslationCache(cache_dir) if cache or settings.cache_dir else None,
    )
    registry = default_registry(configured=settings.tools)

    outcome: RepairResult | None = None
    if repair and dry_run:
        result = translate(source, target, registry=registry, options=options)
        if result.ok:
            eprint("nothing to repair: the shader translated without errors")
            raise typer.Exit(code=EXIT_OK)
        errors = [d for d in result.diagnostics if d.severity is Severity.ERROR]
        tool = (
            result.stages[-1].tool.name if result.stages and result.stages[-1].tool else "unknown"
        )
        prompt = prepare_repair_prompt(source, target, errors, tool=tool)
        request = LlmRequest(
            task="repair_compile_error",
            system=prompt.system,
            user=prompt.user,
            schema=PATCH_SCHEMA,
            prompt_version=prompt_version("system", "repair_compile_error"),
        )
        eprint(
            "DRY RUN: this is exactly what would be sent to the Anthropic API. Nothing was sent."
        )
        eprint(f"files included: {', '.join(prompt.files_sent)}")
        for note in prompt.notes:
            eprint(f"note: {note}")
        typer.echo(request.describe())
        raise typer.Exit(code=EXIT_OK)
    if repair:
        provider = AnthropicProvider(model=settings.llm.model or DEFAULT_MODEL)
        if not quiet:
            eprint(
                "note: if the shader does not compile, its source and the compiler errors "
                "will be sent to the Anthropic API (use --dry-run to preview)"
            )
        outcome = repair_and_translate(
            source,
            target,
            registry=registry,
            provider=provider,
            options=RepairOptions(
                max_attempts=max_attempts or settings.llm.max_attempts,
                allow_large_edits=allow_large_edits,
                translate=options,
            ),
        )
        result = outcome.translation
    else:
        result = translate(source, target, registry=registry, options=options)

    if out is not None and result.ok:
        result.output_path = write_output(result, out, force=force)
    if report is not None:
        findings = None
        if source.path is not None and source.language in (
            ShaderLanguage.HLSL,
            ShaderLanguage.GLSL,
        ):
            try:
                findings = lint_file(
                    source.path, language=source.language, include_dirs=source.include_dirs
                ).findings
            except ShaderFluxError:
                findings = None
        write_report(
            build_report(source, target, result, repair=outcome, findings=findings), report
        )
        if not quiet and not json_output:
            eprint(f"report written to {report}")
    if write_fixed is not None and outcome is not None and outcome.ok and outcome.changed:
        fixed = TranslationResult(ok=True, output_text=outcome.source.text)
        write_output(fixed, write_fixed, force=force)

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        if outcome is not None and outcome.attempts:
            eprint(describe(outcome))
            if outcome.changed:
                eprint("AI-assisted change (review it before using the shader):")
                eprint(outcome.diff)
        for diagnostic in result.diagnostics:
            eprint(diagnostic.format())
        if not result.ok:
            eprint("translation failed")
        elif out is not None:
            if not quiet:
                eprint(f"wrote {out}" + (" (from cache)" if result.cached else ""))
        elif result.output_text is not None:
            typer.echo(result.output_text, nl=not result.output_text.endswith("\n"))
        else:
            raise InvalidInputError("binary output needs --out FILE")

    if (
        not result.ok
        and outcome is not None
        and any(a.outcome is Outcome.LLM_ERROR for a in outcome.attempts)
    ):
        raise typer.Exit(code=EXIT_TOOL)
    raise typer.Exit(code=EXIT_OK if result.ok else EXIT_FAILED)
