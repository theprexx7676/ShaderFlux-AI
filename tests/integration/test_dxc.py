"""Integration tests against a real ``dxc``. Skipped when it is not installed."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.models import ShaderLanguage, ShaderSource, ShaderStage, Target
from shaderflux.tools.dxc import BindingPolicy, DxcBackend
from shaderflux.tools.spirv_tools import SpirvToolsBackend, looks_like_spirv
from tests.conftest import require_tool

pytestmark = [pytest.mark.integration, pytest.mark.needs_tools]

SPIRV = Target(language=ShaderLanguage.SPIRV, environment="vulkan1.2")


def source(corpus: Path, name: str) -> ShaderSource:
    path = corpus / "hlsl" / name
    return ShaderSource(
        path=path, text=path.read_text(), language=ShaderLanguage.HLSL, stage=ShaderStage.FRAGMENT
    )


def test_hlsl_to_valid_spirv(corpus: Path) -> None:
    require_tool("dxc", "spirv-val")
    result = DxcBackend.discover().compile(source(corpus, "textured.hlsl"), target=SPIRV)
    assert result.ok, result.diagnostics
    assert result.output is not None
    assert looks_like_spirv(result.output)
    validation = SpirvToolsBackend.discover().validate(result.output, environment="vulkan1.2")
    assert validation.ok, validation.diagnostics


def test_compile_error_is_located(corpus: Path) -> None:
    require_tool("dxc")
    result = DxcBackend.discover().compile(source(corpus, "broken.hlsl"), target=SPIRV)
    assert not result.ok
    assert any(d.line == 3 and "undefined_thing" in d.message for d in result.errors)


def test_dxil_compiles(corpus: Path) -> None:
    require_tool("dxc")
    result = DxcBackend.discover().check_dxil(source(corpus, "textured.hlsl"))
    assert result.ok, result.diagnostics


def test_binding_shift_flags_are_accepted_by_real_dxc(corpus: Path) -> None:
    """VERIFY item: confirms the -fvk-*-shift syntax we generate."""
    require_tool("dxc")
    policy = BindingPolicy(shifts={"t": 100, "s": 200})
    result = DxcBackend.discover(binding_policy=policy).compile(
        source(corpus, "textured.hlsl"), target=SPIRV
    )
    assert result.ok, result.diagnostics
