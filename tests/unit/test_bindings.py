"""Tests for HLSL binding analysis."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.analysis.bindings import (
    HlslBinding,
    binding_findings,
    find_collisions,
    parse_hlsl_bindings,
    propose_policy,
)
from shaderflux.core.models import Severity

pytestmark = pytest.mark.unit


def b(name: str, reg: str, number: int, space: int = 0, **kw: int) -> HlslBinding:
    return HlslBinding(name=name, reg_type=reg, number=number, space=space, **kw)  # type: ignore[arg-type]


def test_parse_all_declaration_styles() -> None:
    text = """
    cbuffer Params : register(b0) { float4 a; };
    Texture2D tex : register(t1);
    SamplerState samp : register(s0, space2);
    RWStructuredBuffer<float> buf : register(u3);
    Texture2D arr[4] : register(t10);
    ConstantBuffer<Params> cb : register(b1, space1);
    // Texture2D commented : register(t99);
    """
    found = {x.name: (x.reg_type, x.number, x.space) for x in parse_hlsl_bindings(text)}
    assert found == {
        "Params": ("b", 0, 0),
        "tex": ("t", 1, 0),
        "samp": ("s", 0, 2),
        "buf": ("u", 3, 0),
        "arr": ("t", 10, 0),
        "cb": ("b", 1, 1),
    }


def test_parse_records_line_numbers() -> None:
    text = "float a;\n\nTexture2D tex : register(t4);\n"
    (binding,) = parse_hlsl_bindings(text)
    assert binding.line == 3


def test_parse_vk_binding_attribute() -> None:
    text = """
    [[vk::binding(5, 2)]] Texture2D tex;
    [[vk::binding(7)]] SamplerState samp : register(s0);
    [[vk::binding(1)]]
    cbuffer Params { float4 a; };
    """
    found = {x.name: x for x in parse_hlsl_bindings(text)}
    assert (found["tex"].vk_binding, found["tex"].vk_set) == (5, 2)
    assert found["tex"].default_slot() == (2, 5)
    assert (found["samp"].vk_binding, found["samp"].vk_set) == (7, None)
    assert found["samp"].default_slot() == (0, 7)
    assert found["Params"].default_slot() == (0, 1)


def test_default_slot_ignores_register_type() -> None:
    assert b("a", "b", 0).default_slot() == b("a", "t", 0).default_slot() == (0, 0)
    assert b("a", "t", 3, space=2).default_slot() == (2, 3)


def test_collision_between_register_types() -> None:
    (collision,) = find_collisions([b("Params", "b", 0, line=2), b("albedo", "t", 0, line=7)])
    assert collision.slot == (0, 0)
    assert collision.names == ["Params", "albedo"]
    assert collision.registers == ["b0", "t0"]
    assert collision.line == 2


def test_no_collision_across_spaces_or_numbers() -> None:
    assert find_collisions([b("a", "b", 0), b("c", "t", 1), b("d", "t", 0, space=1)]) == []


def test_shifts_remove_collisions() -> None:
    items = [b("a", "b", 0), b("c", "t", 0)]
    assert find_collisions(items)
    assert find_collisions(items, shifts={"t": 10}) == []


def test_vk_attribute_beats_shift() -> None:
    items = [b("a", "t", 0, vk_binding=5), b("c", "t", 0)]
    assert find_collisions(items, shifts={"t": 5}) != []  # c moves onto 5, where a is pinned


def test_propose_policy_on_corpus_shader(corpus: Path) -> None:
    bindings = parse_hlsl_bindings((corpus / "hlsl" / "collision.hlsl").read_text())
    plan = propose_policy(bindings)
    assert [c.names for c in plan.collisions] == [["Params", "albedo", "samp", "output"]]
    assert plan.policy is not None
    # b gets [0], t gets [1..2] (shift 1), s gets [3] (shift 3), u gets [4] (shift 4)
    assert plan.policy.shifts == {"t": 1, "s": 3, "u": 4}
    assert plan.unresolved == []
    assert find_collisions(bindings, shifts=plan.policy.shifts) == []


def test_propose_policy_without_collisions_returns_no_policy() -> None:
    plan = propose_policy([b("a", "b", 0), b("c", "t", 1)])
    assert plan.collisions == []
    assert plan.policy is None


def test_unresolvable_vk_clash_is_reported() -> None:
    items = [b("a", "t", 0, vk_binding=3), b("c", "t", 1, vk_binding=3)]
    plan = propose_policy(items)
    assert plan.collisions
    assert plan.unresolved
    rules = {f.rule for f in binding_findings(plan)}
    assert "BND002" in rules


def test_findings_have_a_concrete_fix(corpus: Path) -> None:
    plan = propose_policy(parse_hlsl_bindings((corpus / "hlsl" / "collision.hlsl").read_text()))
    (finding, *rest) = binding_findings(plan, file="collision.hlsl")
    assert rest == []
    assert finding.rule == "BND001"
    assert finding.severity is Severity.ERROR
    assert finding.suggestion is not None
    assert "-fvk-t-shift 1 all" in finding.suggestion
    assert "register type" in finding.message
    assert finding.file == "collision.hlsl"
