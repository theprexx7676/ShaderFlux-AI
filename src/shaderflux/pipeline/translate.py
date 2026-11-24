"""The deterministic translation pipeline (no LLM involved)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from shaderflux.core.errors import InvalidInputError, ShaderFluxError
from shaderflux.core.logging import get_logger, new_run_id
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    StageResult,
    Target,
    ToolInfo,
    TranslationResult,
)
from shaderflux.pipeline.cache import TranslationCache, make_key
from shaderflux.pipeline.includes import build_include_graph
from shaderflux.pipeline.routes import HopKind, plan_route
from shaderflux.tools.base import BackendRegistry, CrossOptions, ToolResult
from shaderflux.verify.recompile import recheck_generated

DEFAULT_SPIRV_ENVIRONMENT = "vulkan1.2"


@dataclass
class TranslateOptions:
    """Switches for :func:`translate`."""

    roundtrip: bool = False
    validate: bool = True
    cross: CrossOptions | None = None
    cache: TranslationCache | None = None
    recheck: bool = True  # compile the generated GLSL/HLSL again to confirm it is accepted


def _fingerprint(backend: object) -> str:
    """Identify a tool well enough to invalidate cache entries when it changes."""
    name = getattr(backend, "name", type(backend).__name__)
    version = getattr(backend, "version", None) or getattr(backend, "val_version", None)
    if version:
        return f"{name}={version}"
    path = getattr(backend, "path", None) or getattr(backend, "val_path", None)
    try:
        stat = Path(path).stat() if path else None
    except OSError:
        stat = None
    return f"{name}=?{stat.st_mtime_ns}:{stat.st_size}" if stat else f"{name}=?"


def _fail(
    stages: list[StageResult], run_id: str, name: str, message: str, tool: str | None = None
) -> TranslationResult:
    stages.append(
        StageResult(
            name=name,
            ok=False,
            diagnostics=[Diagnostic(severity=Severity.ERROR, message=message, tool=tool)],
        )
    )
    return TranslationResult(ok=False, stages=stages, run_id=run_id)


def translate(
    source: ShaderSource,
    target: Target,
    *,
    registry: BackendRegistry,
    options: TranslateOptions | None = None,
) -> TranslationResult:
    """Translate ``source`` to ``target`` using only deterministic tools.

    Stops at the first failing step and returns everything that was learned.
    Expected failures (compile errors, missing tools) come back as a result with
    ``ok=False``; only misuse raises.
    """
    options = options or TranslateOptions()
    run_id = new_run_id()
    log = get_logger(run_id)
    stages: list[StageResult] = []

    hops = plan_route(source.language, target.language, roundtrip=options.roundtrip)
    log.debug("route: %s", " | ".join(str(h) for h in hops))

    # 1. includes: report problems early and hash the files that affect the result
    include_fingerprint: list[str] = []
    if source.path is not None and source.language in (ShaderLanguage.HLSL, ShaderLanguage.GLSL):
        graph = build_include_graph(source.path, source.include_dirs)
        stages.append(
            StageResult(name="includes", ok=graph.ok, diagnostics=list(graph.diagnostics))
        )
        if not graph.ok:
            return TranslationResult(ok=False, stages=stages, run_id=run_id)
        for file in graph.files:
            if file != graph.root:
                digest = hashlib.sha256(file.read_bytes()).hexdigest()
                include_fingerprint.append(f"{file.name}:{digest}")

    # 2. pick backends up front so missing tools are reported before any work
    try:
        compiler = (
            registry.compiler_for(source.language) if hops[0].kind is HopKind.COMPILE else None
        )
        cross = (
            registry.cross_compiler_for(target.language) if hops[-1].kind is HopKind.CROSS else None
        )
        validator = None
        if options.validate:
            try:
                validator = registry.validator()
            except ShaderFluxError:
                validator = None
    except ShaderFluxError as exc:
        return _fail(stages, run_id, "tools", str(exc))

    # 3. cache
    cache_key = None
    if options.cache is not None:
        cache_key = make_key(
            [
                source.content_hash,
                target.model_dump_json(),
                repr(options.roundtrip),
                repr(options.validate),
                repr(options.recheck),
                repr(options.cross),
                *sorted(include_fingerprint),
                *(_fingerprint(b) for b in (compiler, cross, validator) if b is not None),
            ]
        )
        hit = options.cache.get(cache_key)
        if hit is not None:
            log.debug("cache hit %s", cache_key[:12])
            hit.run_id = run_id
            return hit

    # 4. run the hops
    spirv: bytes | None = source.binary if source.language is ShaderLanguage.SPIRV else None
    if source.language is ShaderLanguage.SPIRV and spirv is None:
        raise InvalidInputError("SPIR-V input has no binary data")
    environment = target.environment or DEFAULT_SPIRV_ENVIRONMENT
    output_text: str | None = None

    def record(name: str, result: ToolResult) -> bool:
        stages.append(result.to_stage(name))
        log.debug("%s: ok=%s (%s)", name, result.ok, result.tool.name)
        return result.ok

    for hop in hops:
        if hop.kind is HopKind.COMPILE:
            assert compiler is not None
            result = compiler.compile(
                source, target=Target(language=ShaderLanguage.SPIRV, environment=environment)
            )
            if not record(f"compile {hop.source.value}", result):
                return TranslationResult(ok=False, stages=stages, run_id=run_id)
            spirv = result.output

            if validator is not None and spirv is not None:
                check = validator.validate(spirv, environment=environment)
                if not record("validate spirv", check):
                    return TranslationResult(ok=False, stages=stages, run_id=run_id)
            elif options.validate:
                stages.append(
                    StageResult(
                        name="validate spirv",
                        ok=True,
                        tool=ToolInfo(name="none"),
                        diagnostics=[
                            Diagnostic(
                                severity=Severity.WARNING,
                                message="spirv-val not found; the SPIR-V was not validated",
                            )
                        ],
                    )
                )
        else:
            assert cross is not None
            assert spirv is not None
            result = cross.convert(spirv, target, options.cross)
            if not record(f"convert to {hop.target.value}", result):
                return TranslationResult(ok=False, stages=stages, run_id=run_id)
            output_text = result.text

    if options.recheck and output_text is not None:
        rechecked = recheck_generated(
            output_text, source, target, registry, environment=environment
        )
        if rechecked is not None:
            stages.append(rechecked)
            log.debug("recheck: ok=%s", rechecked.ok)
            if not rechecked.ok:
                return TranslationResult(
                    ok=False, output_text=output_text, stages=stages, run_id=run_id
                )

    final = TranslationResult(
        ok=True,
        output_text=output_text,
        output_bytes=spirv if target.language is ShaderLanguage.SPIRV else None,
        stages=stages,
        run_id=run_id,
    )
    if options.cache is not None and cache_key is not None:
        options.cache.put(cache_key, final)
    return final
