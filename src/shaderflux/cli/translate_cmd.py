"""``shaderflux translate``."""

from __future__ import annotations

from pathlib import Path

import platformdirs
import typer

from shaderflux.cli.errors import EXIT_FAILED, EXIT_OK, eprint, handle_errors
from shaderflux.core.config import load_settings
from shaderflux.core.errors import InvalidInputError
from shaderflux.core.logging import setup_logging
from shaderflux.core.models import ShaderLanguage, Target
from shaderflux.pipeline.cache import TranslationCache
from shaderflux.pipeline.inputs import load_source, parse_language_name, parse_stage_name
from shaderflux.pipeline.output import write_output
from shaderflux.pipeline.translate import TranslateOptions, translate
from shaderflux.tools.base import CrossOptions
from shaderflux.tools.registry import default_registry


def parse_define(raw: str) -> tuple[str, str | None]:
    """``NAME`` or ``NAME=VALUE``."""
    name, sep, value = raw.partition("=")
    if not name:
        raise InvalidInputError(f"invalid define {raw!r}; use NAME or NAME=VALUE")
    return name, (value if sep else None)


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
    cache: bool = typer.Option(False, "--cache", help="Reuse results of identical runs."),
    json_output: bool = typer.Option(False, "--json", help="Print the full result as JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Translate a shader to another language using the deterministic tool chain."""
    setup_logging(verbose=verbose, quiet=quiet)
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
        cross=CrossOptions(vulkan_semantics=vulkan),
        cache=TranslationCache(cache_dir) if cache or settings.cache_dir else None,
    )
    registry = default_registry(configured=settings.tools)
    result = translate(source, target, registry=registry, options=options)

    if out is not None and result.ok:
        result.output_path = write_output(result, out, force=force)

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
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

    raise typer.Exit(code=EXIT_OK if result.ok else EXIT_FAILED)
