"""Reflection parsing tests using JSON captured from the real SPIRV-Cross."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.analysis.reflection import ResourceKind, parse_reflection
from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import ShaderStage

pytestmark = pytest.mark.unit


@pytest.fixture
def rich(corpus: Path):  # type: ignore[no-untyped-def]
    return parse_reflection((corpus / "reflection" / "rich.json").read_text())


def test_entry_point_and_io(rich) -> None:  # type: ignore[no-untyped-def]
    (entry,) = rich.entry_points
    assert (entry.name, entry.stage) == ("main", ShaderStage.FRAGMENT)
    assert [(i.name, i.location) for i in rich.inputs] == [("uv", 0), ("mode", 1)]
    assert [(o.name, o.type) for o in rich.outputs] == [("color", "vec4")]


def test_every_resource_kind_is_recognised(rich) -> None:  # type: ignore[no-untyped-def]
    kinds = {r.name: r.kind for r in rich.resources}
    assert kinds == {
        "Params": ResourceKind.UNIFORM_BUFFER,
        "Data": ResourceKind.STORAGE_BUFFER,
        "tex": ResourceKind.SAMPLED_IMAGE,
        "samp": ResourceKind.SAMPLER,
        "combined": ResourceKind.COMBINED_IMAGE_SAMPLER,
        "img": ResourceKind.STORAGE_IMAGE,
        "pc": ResourceKind.PUSH_CONSTANT,
    }


def test_slots(rich) -> None:  # type: ignore[no-untyped-def]
    slots = {name: r.slot for name in ("Params", "tex", "samp", "combined", "img", "Data")
             if (r := rich.find(name))}  # fmt: skip
    assert slots == {
        "Params": (0, 0),
        "tex": (0, 1),
        "samp": (0, 2),
        "combined": (1, 0),
        "img": (1, 1),
        "Data": (2, 0),
    }
    pc = rich.find("pc")
    assert pc is not None
    assert pc.slot is None  # push constants have no set/binding


def test_uniform_block_layout(rich) -> None:  # type: ignore[no-untyped-def]
    params = rich.find("Params")
    assert params is not None
    assert params.type == "Params"
    assert params.block_size == 144
    mvp, tint, weights = params.members
    assert (mvp.name, mvp.type, mvp.offset, mvp.matrix_stride) == ("mvp", "mat4", 0, 16)
    assert (tint.type, tint.offset) == ("vec4", 64)
    assert weights.array == [4]
    assert weights.array_stride == 16
    assert weights.offset == 80


def test_storage_image_flags(rich) -> None:  # type: ignore[no-untyped-def]
    img = rich.find("img")
    assert img is not None
    assert img.readonly is True
    assert img.format == "rgba8"


def test_compute_workgroup_size(corpus: Path) -> None:
    reflection = parse_reflection((corpus / "reflection" / "workgroup.json").read_text())
    (entry,) = reflection.entry_points
    assert entry.stage is ShaderStage.COMPUTE
    assert entry.workgroup_size == (8, 4, 1)


def test_by_slot_groups_collisions() -> None:
    text = (
        '{"ubos":[{"type":"_1","name":"A","set":0,"binding":0,"block_size":16}],'
        '"separate_images":[{"type":"texture2D","name":"B","set":0,"binding":0}],'
        '"types":{"_1":{"name":"A","members":[]}}}'
    )
    reflection = parse_reflection(text)
    assert [r.name for r in reflection.by_slot()[(0, 0)]] == ["A", "B"]


def test_row_major_and_nested_structs() -> None:
    text = (
        '{"ubos":[{"type":"_1","name":"U","set":0,"binding":0,"block_size":80}],'
        '"types":{"_1":{"name":"U","members":[{"name":"inner","type":"_2","offset":0},'
        '{"name":"m","type":"mat4","offset":16,"matrix_stride":16,"row_major":true}]},'
        '"_2":{"name":"Inner","members":[{"name":"x","type":"float","offset":0}]}}}'
    )
    block = parse_reflection(text).find("U")
    assert block is not None
    inner, matrix = block.members
    assert inner.type == "Inner"
    assert [m.name for m in inner.members] == ["x"]
    assert matrix.row_major is True


def test_self_referencing_types_do_not_loop() -> None:
    text = (
        '{"ubos":[{"type":"_1","name":"U","set":0,"binding":0}],'
        '"types":{"_1":{"name":"U","members":[{"name":"me","type":"_1","offset":0}]}}}'
    )
    assert parse_reflection(text).find("U") is not None


def test_bad_input() -> None:
    with pytest.raises(InvalidInputError, match="JSON"):
        parse_reflection("not json")
    with pytest.raises(InvalidInputError, match="shape"):
        parse_reflection("[1, 2]")
    assert parse_reflection("{}").resources == []
