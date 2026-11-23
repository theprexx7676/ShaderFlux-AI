"""GLSL to SPIR-V backends: glslangValidator and glslc."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    Target,
)
from shaderflux.tools.base import (
    ToolResult,
    check_spirv_env,
    define_args,
    display_name,
    finish,
    locate,
    tool_info,
)
from shaderflux.tools.runner import run_tool, workspace

_GLSLANG_STAGE = {
    ShaderStage.VERTEX: "vert",
    ShaderStage.TESS_CONTROL: "tesc",
    ShaderStage.TESS_EVALUATION: "tese",
    ShaderStage.GEOMETRY: "geom",
    ShaderStage.FRAGMENT: "frag",
    ShaderStage.COMPUTE: "comp",
    ShaderStage.MESH: "mesh",
    ShaderStage.TASK: "task",
}

_GLSLANG_LINE = re.compile(r"^(ERROR|WARNING|NOTE):\s+(?P<file>.+?):(?P<line>\d+):\s*(?P<msg>.*)$")
_GLSLANG_PLAIN = re.compile(r"^(ERROR|WARNING|NOTE):\s*(?P<msg>.*)$")
_GLSLANG_NOISE = re.compile(r"^\d+ compilation errors?\.|^No code generated")
_GLSLC_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):\s*(?P<sev>error|warning|note):\s*(?P<msg>.*)$"
)
_GLSLC_PLAIN = re.compile(r"^(?P<sev>error|warning):\s*(?P<msg>.*)$")
_GLSLC_NOISE = re.compile(r"^\d+ (errors?|warnings?) generated\.?$|^\d+ warnings? and \d+ errors?")

_SEVERITY = {
    "ERROR": Severity.ERROR,
    "WARNING": Severity.WARNING,
    "NOTE": Severity.NOTE,
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "note": Severity.NOTE,
}


def parse_glslang_diagnostics(text: str, *, tool: str = "glslangValidator") -> list[Diagnostic]:
    """Parse glslangValidator output (``ERROR: file:line: message``)."""
    found: list[Diagnostic] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _GLSLANG_NOISE.match(line.removeprefix("ERROR:").strip()):
            continue
        match = _GLSLANG_LINE.match(line)
        if match:
            found.append(
                Diagnostic(
                    severity=_SEVERITY[match.group(1)],
                    message=match.group("msg").strip(),
                    file=match.group("file"),
                    line=int(match.group("line")),
                    tool=tool,
                )
            )
            continue
        plain = _GLSLANG_PLAIN.match(line)
        if plain:
            found.append(
                Diagnostic(
                    severity=_SEVERITY[plain.group(1)],
                    message=plain.group("msg").strip(),
                    tool=tool,
                )
            )
    return found


def parse_glslc_diagnostics(text: str, *, tool: str = "glslc") -> list[Diagnostic]:
    """Parse glslc output (``file:line: error: message``)."""
    found: list[Diagnostic] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _GLSLC_NOISE.match(line):
            continue
        match = _GLSLC_LINE.match(line)
        if match:
            found.append(
                Diagnostic(
                    severity=_SEVERITY[match.group("sev")],
                    message=match.group("msg").strip(),
                    file=match.group("file"),
                    line=int(match.group("line")),
                    tool=tool,
                )
            )
            continue
        plain = _GLSLC_PLAIN.match(line)
        if plain:
            found.append(
                Diagnostic(
                    severity=_SEVERITY[plain.group("sev")],
                    message=plain.group("msg").strip(),
                    tool=tool,
                )
            )
    return found


def _require_glsl_stage(source: ShaderSource) -> ShaderStage:
    if source.language is not ShaderLanguage.GLSL:
        raise InvalidInputError(f"expected GLSL source, got {source.language.value}")
    if source.stage is None:
        raise InvalidInputError("GLSL compilation needs a shader stage (vertex, fragment, ...)")
    return source.stage


def _include_dirs(source: ShaderSource) -> list[Path]:
    dirs = list(source.include_dirs)
    if source.path is not None and source.path.parent not in dirs:
        dirs.append(source.path.parent)
    return dirs


class GlslangBackend:
    """Compile GLSL to SPIR-V with ``glslangValidator``."""

    name = "glslangValidator"
    languages = frozenset({ShaderLanguage.GLSL})

    def __init__(
        self,
        path: Path,
        version: str | None = None,
        *,
        timeout: float = 60.0,
    ) -> None:
        self.path = path
        self.version = version
        self.timeout = timeout

    @classmethod
    def discover(
        cls,
        *,
        configured: Mapping[str, str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> GlslangBackend:
        path, version = locate("glslangValidator", configured=configured, environ=environ)
        return cls(path, version)

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult:
        stage = _require_glsl_stage(source)
        environment = check_spirv_env(target.environment) or "vulkan1.2"
        info = tool_info(self.name, self.path, self.version)

        with workspace() as work:
            src = work / display_name(source, f"shader.{_GLSLANG_STAGE[stage]}")
            src.write_text(source.text, encoding="utf-8")
            out = work / "out.spv"
            args: list[str | Path] = [
                self.path,
                "-V",
                "-S",
                _GLSLANG_STAGE[stage],
                "--target-env",
                environment,
                "-o",
                out,
                *define_args(source.defines),
            ]
            for directory in _include_dirs(source):
                args.append(f"-I{directory}")
            args.append(src.name)
            run = run_tool(args, timeout=self.timeout, cwd=work)
            diagnostics = parse_glslang_diagnostics(run.stdout_text + "\n" + run.stderr_text)
            produced = out.read_bytes() if run.ok and out.exists() else None
        return finish(
            run,
            info=info,
            ok=run.ok and produced is not None,
            output=produced,
            diagnostics=diagnostics,
        )


class GlslcBackend:
    """Compile GLSL to SPIR-V with ``glslc`` (shaderc)."""

    name = "glslc"
    languages = frozenset({ShaderLanguage.GLSL})

    def __init__(self, path: Path, version: str | None = None, *, timeout: float = 60.0) -> None:
        self.path = path
        self.version = version
        self.timeout = timeout

    @classmethod
    def discover(
        cls,
        *,
        configured: Mapping[str, str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> GlslcBackend:
        path, version = locate("glslc", configured=configured, environ=environ)
        return cls(path, version)

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult:
        stage = _require_glsl_stage(source)
        environment = check_spirv_env(target.environment) or "vulkan1.2"
        info = tool_info(self.name, self.path, self.version)

        with workspace() as work:
            src = work / display_name(source, f"shader.{_GLSLANG_STAGE[stage]}")
            src.write_text(source.text, encoding="utf-8")
            out = work / "out.spv"
            args: list[str | Path] = [
                self.path,
                f"-fshader-stage={_GLSLANG_STAGE[stage]}",
                f"--target-env={environment}",
                "-o",
                out,
                *define_args(source.defines),
            ]
            for directory in _include_dirs(source):
                args.extend(["-I", directory])
            args.append(src.name)
            run = run_tool(args, timeout=self.timeout, cwd=work)
            diagnostics = parse_glslc_diagnostics(run.stderr_text + "\n" + run.stdout_text)
            produced = out.read_bytes() if run.ok and out.exists() else None
        return finish(
            run,
            info=info,
            ok=run.ok and produced is not None,
            output=produced,
            diagnostics=diagnostics,
        )
