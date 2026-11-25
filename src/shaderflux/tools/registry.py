"""Build a :class:`BackendRegistry` from the tools installed on this machine."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping

from shaderflux.core.errors import ToolMissingError
from shaderflux.core.models import ShaderLanguage
from shaderflux.tools.base import CompilerBackend, CrossCompilerBackend, ValidatorBackend
from shaderflux.tools.dxc import DxcBackend
from shaderflux.tools.glsl import GlslangBackend, GlslcBackend
from shaderflux.tools.spirv_cross import SpirvCrossBackend
from shaderflux.tools.spirv_tools import SpirvToolsBackend


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


def default_registry(
    *,
    configured: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> BackendRegistry:
    """Register every backend whose tool can be found.

    Missing tools are simply left out; asking the registry for them later
    raises :class:`ToolMissingError`.
    """
    registry = BackendRegistry()
    with contextlib.suppress(ToolMissingError):
        registry.register_compiler(DxcBackend.discover(configured=configured, environ=environ))
    with contextlib.suppress(ToolMissingError):
        registry.register_compiler(GlslangBackend.discover(configured=configured, environ=environ))
    with contextlib.suppress(ToolMissingError):
        registry.register_compiler(GlslcBackend.discover(configured=configured, environ=environ))
    with contextlib.suppress(ToolMissingError):
        registry.register_cross_compiler(
            SpirvCrossBackend.discover(configured=configured, environ=environ)
        )
    with contextlib.suppress(ToolMissingError):
        registry.register_validator(
            SpirvToolsBackend.discover(configured=configured, environ=environ)
        )
    return registry
