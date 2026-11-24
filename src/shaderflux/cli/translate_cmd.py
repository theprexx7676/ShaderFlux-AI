"""``shaderflux translate``: options in, output out. The work is in ``workflows``."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import typer

from shaderflux.cli.errors import EXIT_FAILED, EXIT_OK, EXIT_TOOL, eprint, handle_errors
from shaderflux.core.config import load_settings
from shaderflux.core.errors import InvalidInputError
from shaderflux.core.logging import setup_logging
from shaderflux.core.models import ShaderLanguage
from shaderflux.llm.repair import describe
from shaderflux.source.inputs import parse_language_name, parse_stage_name
from shaderflux.workflows.translate_file import (
    TranslateOutcome,
    TranslateRequest,
    check_request,
    run_translate,
)


def parse_define(raw: str) -> tuple[str, str | None]:
    """``NAME`` or ``NAME=VALUE``."""
    name, sep, value = raw.partition("=")
    if not name:
        raise InvalidInputError(f"invalid define {raw!r}; use NAME or NAME=VALUE")
    return name, (value if sep else None)


def _check_flag_combinations(
    *,
    repair: bool,
    dry_run: bool,
    write_fixed: Path | None,
    allow_large_edits: bool,
    max_attempts: int | None,
) -> None:
    """Repair-only flags given without --repair are an error, not a silent no-op."""
    if repair:
        return
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


def _print_outcome(outcome: TranslateOutcome, *, out: Path | None, quiet: bool) -> None:
    result, repair = outcome.result, outcome.repair
    if repair is not None and repair.attempts:
        eprint(describe(repair))
        if repair.changed:
            eprint("AI-assisted change (review it before using the shader):")
            eprint(repair.diff)
    for diagnostic in result.diagnostics:
        eprint(diagnostic.format())
    if not result.ok:
        eprint("translation failed")
    elif out is not None:
        if not quiet:
            eprint(f"wrote {out}" + (" (from cache)" if result.cached else ""))
    elif result.output_text is not None:
        typer.echo(result.output_text, nl=not result.output_text.endswith("\n"))


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
    shader_model: str | None = typer.Option(
        None, "--hlsl-model", help="For hlsl, e.g. 50 or 60 (default 50)."
    ),
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
    _check_flag_combinations(
        repair=repair,
        dry_run=dry_run,
        write_fixed=write_fixed,
        allow_large_edits=allow_large_edits,
        max_attempts=max_attempts,
    )
    settings = load_settings().settings

    target_language = parse_language_name(to)
    request = TranslateRequest(
        input_file=input_file,
        target_language=target_language,
        target_version={
            ShaderLanguage.GLSL: glsl_version,
            ShaderLanguage.HLSL: shader_model,
            ShaderLanguage.MSL: msl_version,
        }.get(target_language),
        environment=environment or settings.default_environment,
        source_language=parse_language_name(from_) if from_ else None,
        stage=parse_stage_name(stage) if stage else None,
        entry_point=entry,
        defines=dict(parse_define(item) for item in define),
        include_dirs=[*settings.include_dirs, *include],
        tool_paths=settings.tools,
        roundtrip=roundtrip,
        validate=validate,
        recheck=recheck,
        vulkan_semantics=vulkan,
        cache_dir=(settings.cache_dir or Path(platformdirs.user_cache_dir("shaderflux")))
        if cache or settings.cache_dir
        else None,
        out=out,
        force=force,
        report=report,
        repair=repair,
        dry_run=dry_run,
        max_attempts=max_attempts or settings.llm.max_attempts,
        allow_large_edits=allow_large_edits,
        write_fixed=write_fixed,
        model=settings.llm.model,
    )
    check_request(request)  # fail on bad paths before doing any work or spending anything
    if target_language is ShaderLanguage.SPIRV and out is None and not json_output:
        raise InvalidInputError("binary output needs --out FILE")
    if repair and not dry_run and not quiet:
        eprint(
            "note: if the shader does not compile, its source and the compiler errors "
            "will be sent to the Anthropic API (use --dry-run to preview)"
        )

    outcome = run_translate(request)

    if outcome.nothing_to_repair:
        eprint("nothing to repair: the shader translated without errors")
        raise typer.Exit(code=EXIT_OK)
    if outcome.dry_run is not None:
        eprint(
            "DRY RUN: this is exactly what would be sent to the Anthropic API. Nothing was sent."
        )
        eprint(f"files included: {', '.join(outcome.dry_run.files_sent)}")
        for note in outcome.dry_run.notes:
            eprint(f"note: {note}")
        typer.echo(outcome.dry_run.request.describe())
        raise typer.Exit(code=EXIT_OK)

    if outcome.report_path is not None and not quiet and not json_output:
        eprint(f"report written to {outcome.report_path}")
    if json_output:
        typer.echo(outcome.result.model_dump_json(indent=2))
    else:
        _print_outcome(outcome, out=out, quiet=quiet)

    if outcome.model_call_failed:
        raise typer.Exit(code=EXIT_TOOL)
    raise typer.Exit(code=EXIT_OK if outcome.result.ok else EXIT_FAILED)
