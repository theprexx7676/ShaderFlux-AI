"""How far a translation was actually checked.

The words are chosen carefully: "checked" means a real tool ran and accepted the
result. Nothing here claims the shader renders correctly.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field

from shaderflux.core.models import ShaderLanguage, StageResult, Target, TranslationResult


class Level(IntEnum):
    FAILED = 0
    COMPILED = 1  # the source compiled
    VALIDATED = 2  # the intermediate SPIR-V passed spirv-val
    OUTPUT_CHECKED = 3  # the generated GLSL/HLSL was compiled again


class Label(StrEnum):
    FAILED = "failed"
    PARTLY_CHECKED = "partly-checked"
    CHECKED = "checked"


class Assessment(BaseModel):
    level: Level
    label: Label
    checked: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)

    @property
    def summary(self) -> str:
        name = self.level.name.lower().replace("_", " ")
        return f"{self.label.value} (level {self.level.value}: {name})"


# Always true today; these checks are planned (docs/PLAN.md phase 7).
ALWAYS_NOT_CHECKED = (
    "that the translated shader renders the same pixels as the original "
    "(no image or numeric comparison yet)",
    "that its resources match the original's (no reflection comparison yet)",
)


def _real(stage: StageResult | None) -> bool:
    """A stage counts only if a real tool ran it (skipped steps carry the tool name 'none')."""
    return stage is not None and stage.ok and stage.tool is not None and stage.tool.name != "none"


def _tool(stage: StageResult | None) -> str:
    return stage.tool.name if stage is not None and stage.tool is not None else "unknown"


def _find(stages: list[StageResult], prefix: str) -> StageResult | None:
    return next((s for s in stages if s.name.startswith(prefix)), None)


def assess(result: TranslationResult, target: Target) -> Assessment:
    """Work out what was and was not checked, from the recorded stages only."""
    if not result.ok:
        failing = next((s for s in result.stages if not s.ok), None)
        where = f" at '{failing.name}'" if failing else ""
        return Assessment(
            level=Level.FAILED,
            label=Label.FAILED,
            checked=[],
            not_checked=[f"everything after the failure{where}"],
        )

    checked: list[str] = []
    not_checked: list[str] = []
    level = Level.COMPILED

    compile_stage = _find(result.stages, "compile")
    if _real(compile_stage):
        checked.append(f"the source compiled ({_tool(compile_stage)})")
    validate = _find(result.stages, "validate")
    if _real(validate):
        level = Level.VALIDATED
        checked.append("the intermediate SPIR-V passed spirv-val")
    else:
        not_checked.append("SPIR-V validation (spirv-val was not available or was turned off)")

    final_is_spirv = target.language is ShaderLanguage.SPIRV
    recheck = _find(result.stages, "recompile")
    if final_is_spirv:
        pass  # the SPIR-V itself is what spirv-val checked
    elif _real(recheck):
        if level is Level.VALIDATED:
            level = Level.OUTPUT_CHECKED
        language = target.language.value.upper()
        checked.append(f"the generated {language} compiled again ({_tool(recheck)})")
    elif target.language is ShaderLanguage.MSL:
        not_checked.append("the generated MSL (no Metal compiler is used)")
    else:
        language = target.language.value.upper()
        if recheck is not None and recheck.diagnostics:
            not_checked.append(recheck.diagnostics[0].message)
        else:
            not_checked.append(f"the generated {language} was not compiled again (re-check off)")

    not_checked.extend(ALWAYS_NOT_CHECKED)
    complete = level is Level.OUTPUT_CHECKED or (final_is_spirv and level is Level.VALIDATED)
    return Assessment(
        level=level,
        label=Label.CHECKED if complete else Label.PARTLY_CHECKED,
        checked=checked,
        not_checked=not_checked,
    )
