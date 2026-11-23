"""Build a :class:`BackendRegistry` from the tools installed on this machine."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping

from shaderflux.core.errors import ToolMissingError
from shaderflux.tools.base import BackendRegistry
from shaderflux.tools.dxc import DxcBackend
from shaderflux.tools.glsl import GlslangBackend, GlslcBackend
from shaderflux.tools.spirv_cross import SpirvCrossBackend
from shaderflux.tools.spirv_tools import SpirvToolsBackend


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
