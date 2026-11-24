"""Route planning: which tool hops turn one language into another."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from shaderflux.core.errors import UnsupportedRouteError
from shaderflux.core.models import ShaderLanguage


class HopKind(StrEnum):
    COMPILE = "compile"  # source language to SPIR-V
    CROSS = "cross"  # SPIR-V to a source language


@dataclass(frozen=True)
class Hop:
    source: ShaderLanguage
    target: ShaderLanguage
    kind: HopKind

    def __str__(self) -> str:
        return f"{self.source.value} -> {self.target.value} ({self.kind.value})"


_L = ShaderLanguage
EDGES: tuple[Hop, ...] = (
    Hop(_L.HLSL, _L.SPIRV, HopKind.COMPILE),
    Hop(_L.GLSL, _L.SPIRV, HopKind.COMPILE),
    Hop(_L.SPIRV, _L.GLSL, HopKind.CROSS),
    Hop(_L.SPIRV, _L.HLSL, HopKind.CROSS),
    Hop(_L.SPIRV, _L.MSL, HopKind.CROSS),
)


def supported_pairs() -> list[tuple[ShaderLanguage, ShaderLanguage]]:
    """Every (source, target) pair that has a route, without round trips."""
    pairs = []
    for src in ShaderLanguage:
        for dst in ShaderLanguage:
            if src is dst:
                continue
            try:
                plan_route(src, dst)
            except UnsupportedRouteError:
                continue
            pairs.append((src, dst))
    return pairs


def plan_route(
    source: ShaderLanguage, target: ShaderLanguage, *, roundtrip: bool = False
) -> list[Hop]:
    """Return the shortest list of hops from ``source`` to ``target``.

    Translating a language to itself is refused unless ``roundtrip`` is true,
    because it goes through SPIR-V and rewrites the code.
    """
    if source is target and not roundtrip:
        if source is ShaderLanguage.SPIRV:
            raise UnsupportedRouteError("input and target are both SPIR-V; nothing to do")
        raise UnsupportedRouteError(
            f"input and target are both {source.value}. Converting would round-trip through "
            "SPIR-V and rewrite the code; pass --roundtrip if that is what you want"
        )
    if not any(hop.source is source for hop in EDGES):
        raise UnsupportedRouteError(f"{source.value} cannot be used as an input language")
    if not any(hop.target is target for hop in EDGES):
        raise UnsupportedRouteError(f"{target.value} cannot be produced as an output language")

    queue: deque[tuple[ShaderLanguage, list[Hop]]] = deque([(source, [])])
    seen: set[ShaderLanguage] = set()
    while queue:
        node, path = queue.popleft()
        for hop in EDGES:
            if hop.source is not node:
                continue
            new_path = [*path, hop]
            if hop.target is target:
                return new_path
            if hop.target not in seen:
                seen.add(hop.target)
                queue.append((hop.target, new_path))
    raise UnsupportedRouteError(f"no route from {source.value} to {target.value}")
