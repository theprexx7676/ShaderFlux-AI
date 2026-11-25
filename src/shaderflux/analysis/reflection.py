"""Tool-independent shader reflection.

The model is filled from SPIRV-Cross' JSON reflection today, but nothing here
depends on that tool, so another source (SPIRV-Reflect, DXC) could fill it later.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from shaderflux.core.errors import InvalidInputError, ToolFailedError
from shaderflux.core.models import ShaderStage
from shaderflux.tools.spirv_cross import SpirvCrossBackend

_STAGE_BY_MODE = {
    "vert": ShaderStage.VERTEX,
    "frag": ShaderStage.FRAGMENT,
    "comp": ShaderStage.COMPUTE,
    "geom": ShaderStage.GEOMETRY,
    "tesc": ShaderStage.TESS_CONTROL,
    "tese": ShaderStage.TESS_EVALUATION,
    "mesh": ShaderStage.MESH,
    "task": ShaderStage.TASK,
}


class ResourceKind(StrEnum):
    UNIFORM_BUFFER = "uniform_buffer"
    STORAGE_BUFFER = "storage_buffer"
    SAMPLED_IMAGE = "sampled_image"  # a texture without a sampler
    SAMPLER = "sampler"
    COMBINED_IMAGE_SAMPLER = "combined_image_sampler"
    STORAGE_IMAGE = "storage_image"
    PUSH_CONSTANT = "push_constant"


class BlockMember(BaseModel):
    name: str
    type: str
    offset: int | None = None
    array: list[int] = Field(default_factory=list)
    array_stride: int | None = None
    matrix_stride: int | None = None
    row_major: bool = False
    members: list[BlockMember] = Field(default_factory=list)


class Resource(BaseModel):
    kind: ResourceKind
    name: str
    type: str
    set: int | None = None
    binding: int | None = None
    block_size: int | None = None
    readonly: bool | None = None
    format: str | None = None
    members: list[BlockMember] = Field(default_factory=list)

    @property
    def slot(self) -> tuple[int, int] | None:
        """``(set, binding)`` or ``None`` for resources without one (push constants)."""
        if self.binding is None:
            return None
        return (self.set or 0, self.binding)


class StageIO(BaseModel):
    name: str
    type: str
    location: int | None = None


class EntryPoint(BaseModel):
    name: str
    stage: ShaderStage | None = None
    workgroup_size: tuple[int, int, int] | None = None


class Reflection(BaseModel):
    entry_points: list[EntryPoint] = Field(default_factory=list)
    inputs: list[StageIO] = Field(default_factory=list)
    outputs: list[StageIO] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)

    def by_slot(self) -> dict[tuple[int, int], list[Resource]]:
        slots: dict[tuple[int, int], list[Resource]] = {}
        for resource in self.resources:
            if resource.slot is not None:
                slots.setdefault(resource.slot, []).append(resource)
        return slots

    def find(self, name: str) -> Resource | None:
        return next((r for r in self.resources if r.name == name), None)


_SECTIONS: tuple[tuple[str, ResourceKind], ...] = (
    ("ubos", ResourceKind.UNIFORM_BUFFER),
    ("ssbos", ResourceKind.STORAGE_BUFFER),
    ("separate_images", ResourceKind.SAMPLED_IMAGE),
    ("separate_samplers", ResourceKind.SAMPLER),
    ("textures", ResourceKind.COMBINED_IMAGE_SAMPLER),
    ("images", ResourceKind.STORAGE_IMAGE),
    ("push_constants", ResourceKind.PUSH_CONSTANT),
)


def _members(
    type_id: str, types: dict[str, Any], seen: frozenset[str] = frozenset()
) -> list[BlockMember]:
    """Expand a block type into members, following nested structs (cycle safe)."""
    block = types.get(type_id)
    if block is None or type_id in seen:
        return []
    members: list[BlockMember] = []
    for raw in block.get("members", []):
        type_name = str(raw.get("type", ""))
        nested = types.get(type_name)
        members.append(
            BlockMember(
                name=str(raw.get("name", "")),
                type=nested["name"] if nested and "name" in nested else type_name,
                offset=raw.get("offset"),
                array=[int(n) for n in raw.get("array", [])],
                array_stride=raw.get("array_stride"),
                matrix_stride=raw.get("matrix_stride"),
                row_major=bool(raw.get("row_major", False)),
                members=_members(type_name, types, seen | {type_id}) if nested else [],
            )
        )
    return members


def parse_reflection(text: str) -> Reflection:
    """Parse the JSON printed by ``spirv-cross --reflect``."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f"reflection output is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise InvalidInputError("reflection output has an unexpected shape")

    types: dict[str, Any] = data.get("types", {})
    reflection = Reflection()

    for entry in data.get("entryPoints", []):
        size = entry.get("workgroup_size")
        reflection.entry_points.append(
            EntryPoint(
                name=str(entry.get("name", "main")),
                stage=_STAGE_BY_MODE.get(str(entry.get("mode", ""))),
                workgroup_size=tuple(size) if size and len(size) == 3 else None,
            )
        )
    for key, bucket in (("inputs", reflection.inputs), ("outputs", reflection.outputs)):
        for raw in data.get(key, []):
            bucket.append(
                StageIO(
                    name=str(raw.get("name", "")),
                    type=str(raw.get("type", "")),
                    location=raw.get("location"),
                )
            )

    for section, kind in _SECTIONS:
        for raw in data.get(section, []):
            type_id = str(raw.get("type", ""))
            block = types.get(type_id)
            reflection.resources.append(
                Resource(
                    kind=kind,
                    name=str(raw.get("name", "")),
                    type=block["name"] if block and "name" in block else type_id,
                    set=raw.get("set"),
                    binding=raw.get("binding"),
                    block_size=raw.get("block_size"),
                    readonly=raw.get("readonly"),
                    format=raw.get("format"),
                    members=_members(type_id, types) if block else [],
                )
            )
    return reflection


def reflect(spirv: bytes, backend: SpirvCrossBackend) -> Reflection:
    """Reflect a SPIR-V module using SPIRV-Cross."""
    result = backend.reflect(spirv)
    if not result.ok:
        detail = "; ".join(d.message for d in result.errors) or "unknown error"
        raise ToolFailedError("spirv-cross", f"reflection failed: {detail}")
    return parse_reflection(result.text)
