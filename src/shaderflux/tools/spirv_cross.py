"""SPIRV-Cross wrapper: SPIR-V to GLSL / HLSL / MSL and reflection."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import Diagnostic, Severity, ShaderLanguage, ShaderStage, Target
from shaderflux.tools.base import (
    CrossOptions,
    ToolResult,
    check_entry_point,
    finish,
    locate,
    tool_info,
)
from shaderflux.tools.runner import run_tool, workspace

_STAGE_NAME = {
    ShaderStage.VERTEX: "vert",
    ShaderStage.TESS_CONTROL: "tesc",
    ShaderStage.TESS_EVALUATION: "tese",
    ShaderStage.GEOMETRY: "geom",
    ShaderStage.FRAGMENT: "frag",
    ShaderStage.COMPUTE: "comp",
}
_GLSL_VERSION = re.compile(r"^\d{3}$")
_HLSL_MODEL = re.compile(r"^\d{2}$")
_MSL_VERSION = re.compile(r"^\d{5,6}$")
_ERROR_LINE = re.compile(
    r"^(?:(?P<sev>ERROR|WARNING):\s*|SPIRV-Cross threw an exception:\s*)(?P<msg>.*)$"
)


def parse_cross_diagnostics(text: str, *, tool: str = "spirv-cross") -> list[Diagnostic]:
    """Parse SPIRV-Cross error output (``ERROR: ...`` or an exception message)."""
    found: list[Diagnostic] = []
    for raw in text.splitlines():
        line = raw.strip()
        match = _ERROR_LINE.match(line)
        if not match or not match.group("msg"):
            continue
        sev = match.group("sev")
        found.append(
            Diagnostic(
                severity=Severity.WARNING if sev == "WARNING" else Severity.ERROR,
                message=match.group("msg").strip(),
                tool=tool,
            )
        )
    return found


__all__ = ["CrossOptions", "SpirvCrossBackend", "parse_cross_diagnostics"]


class SpirvCrossBackend:
    """Cross-compile SPIR-V with ``spirv-cross``."""

    name = "spirv-cross"
    targets = frozenset({ShaderLanguage.GLSL, ShaderLanguage.HLSL, ShaderLanguage.MSL})

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
    ) -> SpirvCrossBackend:
        path, version = locate("spirv-cross", configured=configured, environ=environ)
        return cls(path, version)

    # -- argument building ----------------------------------------------

    def build_args(self, target: Target, options: CrossOptions) -> list[str]:
        args: list[str] = []
        if target.language is ShaderLanguage.GLSL:
            if target.version is not None:
                if not _GLSL_VERSION.match(target.version):
                    raise InvalidInputError(f"invalid GLSL version {target.version!r} (e.g. 450)")
                args += ["--version", target.version]
            if options.es:
                args.append("--es")
            if options.vulkan_semantics:
                args.append("--vulkan-semantics")
        elif target.language is ShaderLanguage.HLSL:
            args.append("--hlsl")
            if target.version is not None:
                if not _HLSL_MODEL.match(target.version):
                    raise InvalidInputError(
                        f"invalid HLSL shader model {target.version!r} (e.g. 50 or 60)"
                    )
                args += ["--shader-model", target.version]
        elif target.language is ShaderLanguage.MSL:
            args.append("--msl")
            if target.version is not None:
                if not _MSL_VERSION.match(target.version):
                    raise InvalidInputError(f"invalid MSL version {target.version!r} (e.g. 20100)")
                args += ["--msl-version", target.version]
        else:
            raise InvalidInputError(f"cannot convert SPIR-V to {target.language.value}")

        if options.entry_point is not None:
            args += ["--entry", check_entry_point(options.entry_point)]
        if options.stage is not None:
            if options.stage not in _STAGE_NAME:
                raise InvalidInputError(f"stage {options.stage.value} is not supported here")
            args += ["--stage", _STAGE_NAME[options.stage]]
        if options.remove_unused_variables:
            args.append("--remove-unused-variables")
        return args

    # -- operations -----------------------------------------------------

    def convert(
        self, spirv: bytes, target: Target, options: CrossOptions | None = None
    ) -> ToolResult:
        extra = self.build_args(target, options or CrossOptions())
        return self._run(spirv, extra)

    def reflect(self, spirv: bytes) -> ToolResult:
        """Return SPIRV-Cross' JSON reflection of the module."""
        return self._run(spirv, ["--reflect"])

    def _run(self, spirv: bytes, extra: list[str]) -> ToolResult:
        info = tool_info(self.name, self.path, self.version)
        with workspace() as work:
            module = work / "module.spv"
            module.write_bytes(spirv)
            run = run_tool([self.path, module, *extra], timeout=self.timeout, cwd=work)
        diagnostics = parse_cross_diagnostics(run.stderr_text)
        ok = run.ok and bool(run.stdout.strip())
        if not ok and not any(d.severity is Severity.ERROR for d in diagnostics):
            detail = run.stderr_text.strip() or f"exit code {run.returncode}"
            diagnostics.append(Diagnostic(severity=Severity.ERROR, message=detail, tool=self.name))
        return finish(
            run, info=info, ok=ok, output=run.stdout if ok else None, diagnostics=diagnostics
        )
