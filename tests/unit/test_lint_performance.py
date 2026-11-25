"""Hostile and huge inputs must not make the lint hang.

History: a 6,000 character input (a binding attribute followed by whitespace) took
over five seconds, and a 60 KB one over ten minutes, because of a backtracking
regular expression. Another bug made big valid files quadratic by recounting
newlines for every match. These tests keep both fixed.
"""

from __future__ import annotations

import random
import signal
import sys
import time

import pytest

from shaderflux.analysis.autofix import apply_edits, plan_fixes
from shaderflux.analysis.bindings import binding_findings, parse_hlsl_bindings, propose_policy
from shaderflux.analysis.intrinsics import check_intrinsics
from shaderflux.analysis.limits import MAX_LINE_CHARS, MAX_LINT_CHARS, exceeds_limits
from shaderflux.analysis.lint import lint_text
from shaderflux.analysis.matrix_rules import check_matrices
from shaderflux.analysis.rules import get_rule
from shaderflux.analysis.vulkan_glsl import check_vulkan_glsl
from shaderflux.core.models import ShaderLanguage as L
from shaderflux.core.text import LineIndex

pytestmark = pytest.mark.unit

N = 60_000
HARD_STOP_S = 10  # a regression fails here instead of hanging CI
FLOOR_S = 1.5  # anything faster than this is fine, however it scales
MAX_GROWTH = 8  # 4x the input may cost at most 8x: linear is ~4x, quadratic ~16x


def adversarial(n: int) -> dict[str, str]:
    """Hostile inputs of size ``n``."""
    return {
        "whitespace after a binding attribute": "[[vk::binding(1)]] Texture2D t" + " " * n + "x",
        "whitespace inside register": "a : register(" + " " * n + "t0)",
        "whitespace before the colon": "Texture2D t" + " " * n + "x : register(t0);",
        "whitespace in a matrix keyword": "matrix" + " " * n + "x",
        "one long word": "a" * n,
        "many unclosed binding attributes": "[[vk::binding(1)]] a " * (n // 20),
        "many cbuffers without a brace": "cbuffer C " * (n // 10),
        "many unclosed cbuffers": "cbuffer C {" * (n // 12),
        "many mul calls": "mul(" * (n // 3),
        "deeply nested parentheses": "mul(" + "(" * (n // 12) + "a" + ")" * (n // 12) + ", b)",
        "many declarations": "Texture2D t : register(t0);\n" * (n // 3),
        "many matrices": "float4x4 m;\n" * (n // 3),
        "many real mul calls": "float4 f(){ return mul(v, m); }\n" * (n // 6) + "float4x4 m;",
        "unclosed comment": "/*" + "x" * n,
        "slashes": "/" * n,
        "struct spam": "struct S {" * (n // 12) + "ConstantBuffer<S> c;",
        "transpose spam": "transpose(" * (n // 3),
        "unclosed layout groups": "layout(location = 1" * (n // 19),
        "layout without parentheses": "layout " * (n // 7),
        "many uniform blocks": "uniform U {" * (n // 11),
        "many loose uniforms": "uniform float a;\n" * (n // 17),
        "many interface variables": "in vec2 a;\nout vec4 b;\n" * (n // 24),
        "many preprocessor lines": "#if X\n" * (n // 6),
        "preprocessor without newline": "#" + "x" * n,
        "unclosed parentheses": "(" * n,
        "stray closing braces": "}" * n,
        "huge single declaration": "uniform " + "float a, " * (n // 9) + "z;",
    }


ADVERSARIAL = adversarial(N)


def run_rules_directly(text: str, language: L) -> None:
    """Run every rule on ``text`` *without* the size and line-length limits.

    The limits (``lint_text``) would reject most of these single-line inputs before a
    rule ever saw them, so a test that went through them could not detect a slow rule.
    """
    if language is L.HLSL:
        binding_findings(propose_policy(parse_hlsl_bindings(text)))
    check_matrices(text, language)
    check_intrinsics(text, language)
    if language is L.GLSL:
        check_vulkan_glsl(text)
    if language is L.HLSL:
        apply_edits(text, plan_fixes(text).edits)


class _Timeout(Exception):
    pass


def _alarm(_signum: int, _frame: object) -> None:
    raise _Timeout


def _timed(function, *args) -> float:  # type: ignore[no-untyped-def]
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(HARD_STOP_S)
    try:
        started = time.perf_counter()
        function(*args)
        return time.perf_counter() - started
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


needs_alarm = pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs SIGALRM (POSIX)")


def _assert_scales(function, name: str, *args) -> None:  # type: ignore[no-untyped-def]
    """Fast enough, or at least growing no faster than roughly linearly.

    Absolute times depend on the machine and on coverage (CI runs with coverage on, which
    made a tight loop 25x slower), so the real check is how the cost grows with the input.
    """
    small_input, big_input = adversarial(N // 4)[name], ADVERSARIAL[name]
    small = _timed(function, small_input, *args)
    big = _timed(function, big_input, *args)
    assert big < FLOOR_S or big <= MAX_GROWTH * max(small, 0.02), (
        f"{name}: {small:.2f}s for {len(small_input):,} chars, {big:.2f}s for {len(big_input):,}"
    )


@needs_alarm
@pytest.mark.parametrize("language", [L.HLSL, L.GLSL])
@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_every_rule_scales_on_hostile_input(name: str, language: L) -> None:
    """Rules called directly, so the limits cannot hide a slow one."""
    _assert_scales(run_rules_directly, name, language)


@needs_alarm
@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_lint_text_finishes_on_hostile_input_within_the_limits(name: str) -> None:
    """The whole pipeline, with inputs shrunk to just under the line-length limit."""
    text = ADVERSARIAL[name]
    if len(text.split("\n", 1)[0]) > MAX_LINE_CHARS:
        text = text[: MAX_LINE_CHARS - 1]
    assert _timed(lint_text, text, L.HLSL) < HARD_STOP_S, name


def test_the_limits_really_do_short_circuit_long_lines() -> None:
    """Documents why the direct tests above are needed."""
    (finding,) = lint_text(ADVERSARIAL["one long word"], L.HLSL)
    assert finding.rule == "LNT001"


def test_a_large_valid_file_scales_roughly_linearly() -> None:
    def cost(count: int) -> float:
        text = "Texture2D t : register(t0);\nfloat4x4 m;\nfloat4 f(){ return mul(v, m); }\n" * count
        started = time.perf_counter()
        lint_text(text, L.HLSL)
        return time.perf_counter() - started

    small, large = cost(2_000), cost(16_000)  # 8x the input
    assert large < max(small * 40, 3.0), f"{small:.3f}s -> {large:.3f}s is not close to linear"


def test_files_over_the_limits_are_reported_not_analysed() -> None:
    huge = "// c\n" * (MAX_LINT_CHARS // 4)
    assert "characters (limit" in (exceeds_limits(huge) or "")
    long_line = "x" * (MAX_LINE_CHARS + 1)
    assert "line of" in (exceeds_limits(long_line) or "")
    assert exceeds_limits("float4 f() { return 0; }\n" * 100) is None
    (finding,) = lint_text(long_line, L.HLSL, file="gen.hlsl")
    assert finding.rule == "LNT001"
    assert finding.file == "gen.hlsl"
    assert "not analysed" in finding.message


def test_new_rules_are_documented() -> None:
    for rule in ("LNT001", "INC001"):
        assert get_rule(rule) is not None


def test_line_index_agrees_with_naive_counting() -> None:
    rng = random.Random(7)
    for _ in range(300):
        text = "".join(rng.choice("ab\n\n \r") for _ in range(rng.randint(0, 50)))
        index = LineIndex(text)
        for offset in range(len(text) + 1):
            assert index.line_of(offset) == text.count("\n", 0, offset) + 1


def test_line_numbers_are_still_right_in_findings() -> None:
    text = "// one\n\nTexture2D a : register(t0);\n\ncbuffer C : register(b0) { float4 x; };\n"
    (finding,) = [f for f in lint_text(text, L.HLSL) if f.rule == "BND001"]
    assert finding.line == 3  # the earliest of the two colliding declarations


@pytest.mark.skipif(sys.platform == "win32", reason="timing on shared Windows runners is noisy")
def test_long_real_world_file_is_fast() -> None:
    body = "\n".join(
        f"float4 v{i} = mul(float4(1, 2, 3, 4), world{i}); // {i}" for i in range(3000)
    )
    started = time.perf_counter()
    lint_text("float4x4 world0;\n" + body, L.HLSL)
    assert time.perf_counter() - started < HARD_STOP_S
