"""Backend interfaces and helpers shared by all tool wrappers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from shaderflux.core.errors import InvalidInputError, ToolMissingError
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

_DEFINE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENTRY_POINT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SPIRV_ENV = re.compile(
    r"^(vulkan1\.[0-4](spirv1\.[0-6])?|spirv1\.[0-6]|universal1\.[0-6]|opengl)$"
)


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


class BackendRegistry:
    """Lets the pipeline pick backends without importing concrete classes."""

    def __init__(self) -> None:
        self._compilers: list[CompilerBackend] = []
        self._cross: list[CrossCompilerBackend] = []
        self._validators: list[ValidatorBackend] = []

    def register_compiler(self, backend: CompilerBackend) -> None:
        self._compilers.append(backend)

    def register_cross_compiler(self, backend: CrossCompilerBackend) -> None:
        self._cross.append(backend)

    def register_validator(self, backend: ValidatorBackend) -> None:
        self._validators.append(backend)

    def compiler_for(self, language: ShaderLanguage) -> CompilerBackend:
        for backend in self._compilers:
            if language in backend.languages:
                return backend
        raise ToolMissingError(f"a {language.value} compiler")

    def cross_compiler_for(self, language: ShaderLanguage) -> CrossCompilerBackend:
        for backend in self._cross:
            if language in backend.targets:
                return backend
        raise ToolMissingError(f"a SPIR-V to {language.value} converter")

    def validator(self) -> ValidatorBackend:
        if not self._validators:
            raise ToolMissingError("a SPIR-V validator")
        return self._validators[0]


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


def check_define_name(name: str) -> str:
    if not _DEFINE_NAME.match(name):
        raise InvalidInputError(f"invalid macro name: {name!r}")
    return name


def check_define_value(name: str, value: str) -> str:
    if "\0" in value or "\n" in value or "\r" in value:
        raise InvalidInputError(f"macro {name} has a value with a control character")
    return value


def define_args(defines: Mapping[str, str | None], style: str = "-D{}") -> list[str]:
    """Render ``{"A": "1", "B": None}`` as ``["-DA=1", "-DB"]``."""
    args: list[str] = []
    for name, value in defines.items():
        check_define_name(name)
        if value is None:
            args.append(style.format(name))
        else:
            args.append(style.format(f"{name}={check_define_value(name, value)}"))
    return args


def check_entry_point(entry: str) -> str:
    if not _ENTRY_POINT.match(entry):
        raise InvalidInputError(f"invalid entry point name: {entry!r}")
    return entry


def check_spirv_env(environment: str | None) -> str | None:
    if environment is None:
        return None
    if not _SPIRV_ENV.match(environment):
        raise InvalidInputError(
            f"unsupported target environment {environment!r} (examples: vulkan1.2, spirv1.5)"
        )
    return environment


def display_name(source: ShaderSource, default: str) -> str:
    """File name used for the temporary copy, so diagnostics show something meaningful.

    A name that starts with ``-`` would be read by the compiler as an option, so
    leading dashes are removed. Anything unusual in the name becomes ``_``.
    """
    if source.path is not None and source.path.name:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", source.path.name).lstrip("-")
        if name and not name.startswith("."):
            return name
    return default
