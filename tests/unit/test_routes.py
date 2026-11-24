"""Tests for route planning."""

from __future__ import annotations

import pytest

from shaderflux.core.errors import UnsupportedRouteError
from shaderflux.core.models import ShaderLanguage as L
from shaderflux.pipeline.routes import HopKind, plan_route, supported_pairs

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("source", "target", "steps"),
    [
        (L.HLSL, L.SPIRV, [(L.HLSL, L.SPIRV)]),
        (L.GLSL, L.SPIRV, [(L.GLSL, L.SPIRV)]),
        (L.SPIRV, L.GLSL, [(L.SPIRV, L.GLSL)]),
        (L.HLSL, L.GLSL, [(L.HLSL, L.SPIRV), (L.SPIRV, L.GLSL)]),
        (L.GLSL, L.HLSL, [(L.GLSL, L.SPIRV), (L.SPIRV, L.HLSL)]),
        (L.HLSL, L.MSL, [(L.HLSL, L.SPIRV), (L.SPIRV, L.MSL)]),
    ],
)
def test_routes(source: L, target: L, steps: list[tuple[L, L]]) -> None:
    route = plan_route(source, target)
    assert [(h.source, h.target) for h in route] == steps


def test_hop_kinds() -> None:
    route = plan_route(L.HLSL, L.GLSL)
    assert [h.kind for h in route] == [HopKind.COMPILE, HopKind.CROSS]


def test_same_language_needs_explicit_roundtrip() -> None:
    with pytest.raises(UnsupportedRouteError, match="--roundtrip"):
        plan_route(L.HLSL, L.HLSL)
    route = plan_route(L.HLSL, L.HLSL, roundtrip=True)
    assert [(h.source, h.target) for h in route] == [(L.HLSL, L.SPIRV), (L.SPIRV, L.HLSL)]


def test_spirv_to_spirv_is_never_useful() -> None:
    with pytest.raises(UnsupportedRouteError, match="nothing to do"):
        plan_route(L.SPIRV, L.SPIRV)


def test_msl_cannot_be_an_input() -> None:
    with pytest.raises(UnsupportedRouteError, match="input"):
        plan_route(L.MSL, L.GLSL)


def test_supported_pairs_are_consistent() -> None:
    pairs = supported_pairs()
    assert (L.HLSL, L.GLSL) in pairs
    assert (L.GLSL, L.HLSL) in pairs
    assert (L.HLSL, L.HLSL) not in pairs
    assert all(src is not dst for src, dst in pairs)
