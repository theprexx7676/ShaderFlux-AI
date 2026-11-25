"""Core domain models shared by every package."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ShaderLanguage(StrEnum):
    HLSL = "hlsl"
    GLSL = "glsl"
    SPIRV = "spirv"
    MSL = "msl"


class ShaderStage(StrEnum):
    VERTEX = "vertex"
    FRAGMENT = "fragment"
    COMPUTE = "compute"
    GEOMETRY = "geometry"
    TESS_CONTROL = "tess_control"
    TESS_EVALUATION = "tess_evaluation"
    MESH = "mesh"
    TASK = "task"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"


class Diagnostic(BaseModel):
    """A single message produced by a tool or a lint rule."""

    model_config = ConfigDict(frozen=True)

    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    code: str | None = None
    tool: str | None = None

    def format(self) -> str:
        where = ""
        if self.file:
            where = self.file
            if self.line is not None:
                where += f":{self.line}"
                if self.column is not None:
                    where += f":{self.column}"
            where += ": "
        return f"{where}{self.severity.value}: {self.message}"


class ShaderSource(BaseModel):
    """A shader to translate, together with everything needed to compile it."""

    path: Path | None = None
    text: str = ""
    binary: bytes | None = Field(default=None, repr=False, exclude=True)
    language: ShaderLanguage
    stage: ShaderStage | None = None
    entry_point: str = "main"
    defines: dict[str, str | None] = Field(default_factory=dict)
    include_dirs: list[Path] = Field(default_factory=list)

    @property
    def content_hash(self) -> str:
        """Stable hash of everything that affects the compiled result."""
        digest = hashlib.sha256()
        parts = [
            self.language.value,
            self.stage.value if self.stage else "",
            self.entry_point,
            repr(sorted(self.defines.items(), key=lambda item: item[0])),
            self.text,
        ]
        for part in parts:
            digest.update(part.encode("utf-8"))
            digest.update(b"\0")
        if self.binary is not None:
            digest.update(self.binary)
        return digest.hexdigest()


class Target(BaseModel):
    """What to translate to.

    ``version`` is language specific (GLSL ``450``, HLSL shader model ``50``,
    SPIR-V ``1.5``). ``environment`` names the API environment, for example
    ``vulkan1.2``.
    """

    language: ShaderLanguage
    version: str | None = None
    environment: str | None = None


class ToolInfo(BaseModel):
    """Identity of a tool run, recorded for reproducible reports."""

    name: str
    version: str | None = None
    path: str | None = None


class StageResult(BaseModel):
    """Outcome of one step of a translation."""

    name: str
    ok: bool
    tool: ToolInfo | None = None
    command: list[str] = Field(default_factory=list)
    duration_s: float = 0.0
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class TranslationResult(BaseModel):
    """Outcome of a whole translation."""

    ok: bool
    output_text: str | None = None
    output_bytes: bytes | None = Field(default=None, repr=False, exclude=True)
    output_path: Path | None = None
    run_id: str | None = None
    cached: bool = False
    stages: list[StageResult] = Field(default_factory=list)

    @property
    def diagnostics(self) -> list[Diagnostic]:
        return [d for stage in self.stages for d in stage.diagnostics]
