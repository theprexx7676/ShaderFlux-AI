"""Backend interfaces and helpers shared by all tool wrappers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from shaderflux.core.errors import ToolMissingError
from shaderflux.core.models import (
    Diagnostic,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    StageResult,
    Target,
    ToolInfo,
)
from shaderflux.tools.discovery import TOOLS, find_executable, install_hint, read_version
from shaderflux.tools.runner import ToolRun, redact_command


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one backend operation.

    ``output`` holds the produced artefact: SPIR-V bytes, or UTF-8 text for
    source-to-source operations. ``ok`` means the tool succeeded and produced
    output; diagnostics may still contain warnings.
    """

    ok: bool
    output: bytes | None
    diagnostics: tuple[Diagnostic, ...]
    tool: ToolInfo
    command: tuple[str, ...]
    duration_s: float
    stderr: str = ""
    extra: Mapping[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return (self.output or b"").decode("utf-8", errors="replace")

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    def to_stage(self, name: str) -> StageResult:
        return StageResult(
            name=name,
            ok=self.ok,
            tool=self.tool,
            command=list(self.command),
            duration_s=self.duration_s,
            diagnostics=list(self.diagnostics),
        )


@dataclass(frozen=True)
class CrossOptions:
    """Optional switches for the conversion."""

    vulkan_semantics: bool = False
    es: bool = False
    entry_point: str | None = None
    stage: ShaderStage | None = None
    remove_unused_variables: bool = False


@runtime_checkable
class CompilerBackend(Protocol):
    """Compiles shader source to SPIR-V."""

    name: str
    languages: frozenset[ShaderLanguage]

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult: ...


@runtime_checkable
class CrossCompilerBackend(Protocol):
    """Converts SPIR-V to another shading language."""

    name: str
    targets: frozenset[ShaderLanguage]

    def convert(
        self, spirv: bytes, target: Target, options: CrossOptions | None = None
    ) -> ToolResult: ...


@runtime_checkable
class ValidatorBackend(Protocol):
    """Validates SPIR-V."""

    name: str

    def validate(self, spirv: bytes, *, environment: str | None = None) -> ToolResult: ...


def locate(
    key: str,
    *,
    configured: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path, str | None]:
    """Find a tool and its version, or raise :class:`ToolMissingError` with an install hint."""
    spec = TOOLS[key]
    path = find_executable(spec, configured=configured, environ=environ)
    if path is None:
        raise ToolMissingError(key, install_hint(spec))
    return path, read_version(spec, path)


def tool_info(name: str, path: Path, version: str | None) -> ToolInfo:
    return ToolInfo(name=name, version=version, path=str(path))


def finish(
    run: ToolRun,
    *,
    info: ToolInfo,
    ok: bool,
    output: bytes | None,
    diagnostics: Sequence[Diagnostic],
) -> ToolResult:
    """Build a :class:`ToolResult` with a redacted command line."""
    return ToolResult(
        ok=ok,
        output=output,
        diagnostics=tuple(diagnostics),
        tool=info,
        command=tuple(redact_command(run.command)),
        duration_s=run.duration_s,
        stderr=run.stderr_text,
    )
