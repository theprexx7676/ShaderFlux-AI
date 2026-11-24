"""Tests for the backend registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.errors import ToolMissingError
from shaderflux.core.models import ShaderLanguage, ShaderSource, Target
from shaderflux.tools.base import ToolResult
from shaderflux.tools.registry import BackendRegistry, default_registry

pytestmark = pytest.mark.unit


class FakeCompiler:
    name = "fake"
    languages = frozenset({ShaderLanguage.HLSL})

    def compile(self, source: ShaderSource, *, target: Target) -> ToolResult:
        raise NotImplementedError


def test_registry_returns_registered_backend() -> None:
    registry = BackendRegistry()
    fake = FakeCompiler()
    registry.register_compiler(fake)
    assert registry.compiler_for(ShaderLanguage.HLSL) is fake


def test_registry_raises_for_unknown_language() -> None:
    registry = BackendRegistry()
    registry.register_compiler(FakeCompiler())
    with pytest.raises(ToolMissingError):
        registry.compiler_for(ShaderLanguage.GLSL)
    with pytest.raises(ToolMissingError):
        registry.cross_compiler_for(ShaderLanguage.GLSL)
    with pytest.raises(ToolMissingError):
        registry.validator()


def test_default_registry_with_no_tools_is_empty(tmp_path: Path) -> None:
    registry = default_registry(environ={"PATH": str(tmp_path)})
    with pytest.raises(ToolMissingError):
        registry.compiler_for(ShaderLanguage.HLSL)
    with pytest.raises(ToolMissingError):
        registry.validator()
