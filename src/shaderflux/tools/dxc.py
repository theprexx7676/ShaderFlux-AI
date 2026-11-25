"""DirectXShaderCompiler (``dxc``) backend: HLSL to SPIR-V and DXIL.

.. warning::
   This backend was written from DXC's documentation. It has **not** been
   exercised against a real ``dxc`` binary yet (none was installable in the
   development environment). Items marked ``VERIFY`` must be checked against
   ``dxc --help`` and a real compile before this backend is trusted.
   The integration tests in ``tests/integration/test_dxc.py`` do that as soon
   as ``dxc`` is on the ``PATH``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    Target,
)
from shaderflux.tools.base import ToolResult, finish, locate, tool_info
from shaderflux.tools.runner import run_tool, workspace
from shaderflux.tools.validation import (
    check_entry_point,
    check_spirv_env,
    define_args,
    display_name,
)

RegisterType = Literal["b", "t", "s", "u"]

_PROFILE_PREFIX = {
    ShaderStage.VERTEX: "vs",
    ShaderStage.FRAGMENT: "ps",
    ShaderStage.COMPUTE: "cs",
    ShaderStage.GEOMETRY: "gs",
    ShaderStage.TESS_CONTROL: "hs",
    ShaderStage.TESS_EVALUATION: "ds",
    ShaderStage.MESH: "ms",
    ShaderStage.TASK: "as",
}
_SHADER_MODEL = re.compile(r"^\d_\d$")
_DXC_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+):\s*"
    r"(?P<sev>fatal error|error|warning|note):\s*(?P<msg>.*)$"
)
_DXC_PLAIN = re.compile(r"^(?P<sev>fatal error|error|warning):\s*(?P<msg>.*)$")
_SEVERITY = {
    "fatal error": Severity.ERROR,
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "note": Severity.NOTE,
}


class RegisterBinding(BaseModel):
    """Explicit mapping of one HLSL register to a Vulkan descriptor."""

    reg_type: RegisterType
    number: int = Field(ge=0)
    space: int = Field(default=0, ge=0)
    binding: int = Field(ge=0)
    descriptor_set: int = Field(default=0, ge=0)


class BindingPolicy(BaseModel):
    """How HLSL registers are mapped to Vulkan ``set``/``binding`` pairs.

    Two mutually exclusive strategies, matching DXC's documented restriction
    that ``-fvk-*-shift`` and ``-fvk-bind-register`` cannot be combined:

    * ``shifts``: add a constant to every register number of one type, so that
      ``b``, ``t``, ``s`` and ``u`` registers stop colliding;
    * ``explicit``: spell out each register's binding.

    VERIFY: the exact option syntax below against ``dxc --help``.
    """

    shifts: dict[RegisterType, int] = Field(default_factory=dict)
    shift_space: int | Literal["all"] = "all"
    explicit: list[RegisterBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exclusive(self) -> BindingPolicy:
        if self.shifts and self.explicit:
            raise ValueError("shifts and explicit bindings cannot be combined (DXC restriction)")
        if any(value < 0 for value in self.shifts.values()):
            raise ValueError("shift values must not be negative")
        return self

    def to_args(self) -> list[str]:
        args: list[str] = []
        for reg_type, amount in sorted(self.shifts.items()):
            args += [f"-fvk-{reg_type}-shift", str(amount), str(self.shift_space)]
        for item in self.explicit:
            args += [
                "-fvk-bind-register",
                f"{item.reg_type}{item.number}",
                str(item.space),
                str(item.binding),
                str(item.descriptor_set),
            ]
        return args


def parse_dxc_diagnostics(text: str, *, tool: str = "dxc") -> list[Diagnostic]:
    """Parse clang-style DXC diagnostics (``file:line:col: error: message``)."""
    found: list[Diagnostic] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        match = _DXC_LINE.match(line)
        if match:
            found.append(
                Diagnostic(
                    severity=_SEVERITY[match.group("sev")],
                    message=match.group("msg").strip(),
                    file=match.group("file"),
                    line=int(match.group("line")),
                    column=int(match.group("col")),
                    tool=tool,
                )
            )
            continue
        plain = _DXC_PLAIN.match(line)
        if plain:
            found.append(
                Diagnostic(
                    severity=_SEVERITY[plain.group("sev")],
                    message=plain.group("msg").strip(),
                    tool=tool,
                )
            )
    return found


def profile_for(stage: ShaderStage, shader_model: str) -> str:
    """Build a DXC target profile such as ``ps_6_0``."""
    if not _SHADER_MODEL.match(shader_model):
        raise InvalidInputError(f"invalid shader model {shader_model!r} (use e.g. 6_0)")
    return f"{_PROFILE_PREFIX[stage]}_{shader_model}"


class DxcBackend:
    """Compile HLSL with ``dxc``."""

    name = "dxc"
    languages = frozenset({ShaderLanguage.HLSL})

    def __init__(
        self,
        path: Path,
        version: str | None = None,
        *,
        shader_model: str = "6_0",
        binding_policy: BindingPolicy | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.path = path
        self.version = version
        self.shader_model = shader_model
        self.binding_policy = binding_policy or BindingPolicy()
        self.timeout = timeout

    @classmethod
    def discover(
        cls,
        *,
        configured: Mapping[str, str] | None = None,
        environ: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> DxcBackend:
        path, version = locate("dxc", configured=configured, environ=environ)
        return cls(path, version, **kwargs)  # type: ignore[arg-type]

    # -- argument building ----------------------------------------------

    def build_args(
        self, source: ShaderSource, *, spirv: bool, environment: str | None = None
    ) -> list[str]:
        if source.language is not ShaderLanguage.HLSL:
            raise InvalidInputError(f"expected HLSL source, got {source.language.value}")
        if source.stage is None:
            raise InvalidInputError("HLSL compilation needs a shader stage (vertex, pixel, ...)")
        args = [
            "-T",
            profile_for(source.stage, self.shader_model),
            "-E",
            check_entry_point(source.entry_point),
        ]
        if spirv:
            args.append("-spirv")
            env = check_spirv_env(environment)
            if env:
                args.append(f"-fspv-target-env={env}")  # VERIFY spelling of accepted values
            args += self.binding_policy.to_args()
        args += define_args(source.defines)
        dirs = list(source.include_dirs)
        if source.path is not None and source.path.parent not in dirs:
            dirs.append(source.path.parent)
        for directory in dirs:
            args += ["-I", str(directory)]
        return args

    # -- operations -----------------------------------------------------

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult:
        """Compile to SPIR-V."""
        if target.language is not ShaderLanguage.SPIRV:
            raise InvalidInputError("DxcBackend.compile produces SPIR-V; use check_dxil for DXIL")
        return self._run(source, spirv=True, environment=target.environment)

    def check_dxil(self, source: ShaderSource) -> ToolResult:
        """Compile to DXIL, to answer "does this build for Direct3D 12?"."""
        return self._run(source, spirv=False, environment=None)

    def _run(self, source: ShaderSource, *, spirv: bool, environment: str | None) -> ToolResult:
        extra = self.build_args(source, spirv=spirv, environment=environment)
        info = tool_info(self.name, self.path, self.version)
        with workspace() as work:
            src = work / display_name(source, "shader.hlsl")
            src.write_text(source.text, encoding="utf-8")
            out = work / ("out.spv" if spirv else "out.dxil")
            args: list[str | Path] = [self.path, *extra, "-Fo", out, src.name]
            run = run_tool(args, timeout=self.timeout, cwd=work)
            produced = out.read_bytes() if run.ok and out.exists() else None
        diagnostics = parse_dxc_diagnostics(run.stderr_text + "\n" + run.stdout_text)
        if not run.ok and not any(d.severity is Severity.ERROR for d in diagnostics):
            detail = (run.stderr_text or run.stdout_text).strip() or f"exit code {run.returncode}"
            diagnostics.append(Diagnostic(severity=Severity.ERROR, message=detail, tool=self.name))
        return finish(
            run, info=info, ok=produced is not None, output=produced, diagnostics=diagnostics
        )
