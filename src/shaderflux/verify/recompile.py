"""Re-check generated source by compiling it again with a real compiler.

Validating the intermediate SPIR-V does not prove that the generated GLSL or HLSL
is accepted by its own compiler. This step closes that gap where a compiler is
available, and says so plainly where it is not.
"""

from __future__ import annotations

from shaderflux.core.errors import ShaderFluxError
from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    StageResult,
    Target,
    ToolInfo,
)
from shaderflux.tools.base import BackendRegistry


def recheck_generated(
    text: str,
    source: ShaderSource,
    target: Target,
    registry: BackendRegistry,
    *,
    environment: str,
) -> StageResult | None:
    """Compile ``text`` (the generated shader) and report the outcome.

    Returns ``None`` when the target language cannot be re-checked at all (SPIR-V
    is already validated; MSL has no compiler here).
    """
    language = target.language
    if language not in (ShaderLanguage.GLSL, ShaderLanguage.HLSL):
        return None
    name = f"recompile generated {language.value}"

    def skipped(reason: str) -> StageResult:
        return StageResult(
            name=name,
            ok=True,
            tool=ToolInfo(name="none"),
            diagnostics=[Diagnostic(severity=Severity.WARNING, message=reason)],
        )

    if source.stage is None:
        return skipped("the shader stage is unknown, so the generated code was not recompiled")
    try:
        compiler = registry.compiler_for(language)
    except ShaderFluxError:
        tool = "dxc" if language is ShaderLanguage.HLSL else "glslangValidator or glslc"
        return skipped(
            f"{tool} was not found, so the generated {language.value.upper()} was not recompiled"
        )

    generated = ShaderSource(
        text=text,
        language=language,
        stage=source.stage,
        entry_point="main",
        include_dirs=[],
    )
    result = compiler.compile(
        generated, target=Target(language=ShaderLanguage.SPIRV, environment=environment)
    )
    stage = result.to_stage(name)
    if not result.ok and language is ShaderLanguage.GLSL:
        stage.diagnostics.append(
            Diagnostic(
                severity=Severity.NOTE,
                message=(
                    "the generated GLSL does not compile as Vulkan GLSL; "
                    "try --vulkan (Vulkan-style output)"
                ),
            )
        )
    return stage
