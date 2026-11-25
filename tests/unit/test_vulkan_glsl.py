"""Vulkan GLSL rules (VKG001 to VKG004): what we flag, and what we must leave alone."""

from __future__ import annotations

import pytest

from shaderflux.analysis.findings import Confidence
from shaderflux.analysis.lint import lint_text
from shaderflux.analysis.vulkan_glsl import check_vulkan_glsl
from shaderflux.core.models import ShaderLanguage
from tests.vulkan_glsl_cases import CASES

pytestmark = pytest.mark.unit

GLSL = ShaderLanguage.GLSL


@pytest.mark.parametrize(("name", "ext", "source", "expected"), CASES, ids=[c[0] for c in CASES])
def test_each_case_reports_exactly_the_expected_rules(
    name: str, ext: str, source: str, expected: frozenset[str]
) -> None:
    assert {f.rule for f in check_vulkan_glsl(source)} == expected


def test_findings_carry_a_concrete_fix_and_a_line() -> None:
    source = "#version 450\n\nuniform float gain;\nvoid main() {}\n"
    (finding,) = check_vulkan_glsl(source, file="a.frag")
    assert (finding.rule, finding.line, finding.file) == ("VKG002", 3, "a.frag")
    assert finding.suggestion
    assert "uniform" in finding.suggestion


def test_the_first_declarator_is_named() -> None:
    (finding,) = check_vulkan_glsl("uniform vec4 first, second;\n")
    assert "'first'" in finding.message


def test_conditional_compilation_lowers_confidence() -> None:
    plain = check_vulkan_glsl("uniform float g;\n")
    guarded = check_vulkan_glsl("#ifdef GL\nuniform float g;\n#endif\n")
    assert plain[0].confidence is Confidence.HIGH
    assert guarded[0].confidence is Confidence.MEDIUM


def test_preprocessor_lines_do_not_leak_into_the_next_declaration() -> None:
    source = "#version 450\n#extension GL_EXT_scalar_block_layout : enable\nuniform float g;\n"
    (finding,) = check_vulkan_glsl(source)
    assert finding.line == 3


def test_declarations_inside_function_bodies_are_ignored() -> None:
    source = "void main() {\n    float uniform_like = 1.0;\n    in_flight();\n}\n"
    assert check_vulkan_glsl(source) == []


def test_only_glsl_that_targets_vulkan_is_checked() -> None:
    source = "uniform float gain;\nvoid main() {}\n"
    assert {f.rule for f in lint_text(source, GLSL)} == {"VKG002"}
    assert lint_text(source, GLSL, vulkan=False) == []
    assert lint_text(source, ShaderLanguage.HLSL) == []


def test_empty_and_odd_input_does_not_crash() -> None:
    for text in (
        "",
        "   \n",
        "uniform",
        "layout(",
        "layout(location = ) in",
        "in vec2 {",
        ";;;",
        "}",
    ):
        check_vulkan_glsl(text)
