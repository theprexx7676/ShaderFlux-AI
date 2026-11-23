"""Parser tests using output captured from the real tools."""

from __future__ import annotations

import pytest

from shaderflux.core.models import Severity
from shaderflux.tools.glsl import parse_glslang_diagnostics, parse_glslc_diagnostics
from shaderflux.tools.spirv_cross import parse_cross_diagnostics
from shaderflux.tools.spirv_tools import (
    looks_like_spirv,
    parse_validator_diagnostics,
    to_spirv_tools_env,
)

pytestmark = pytest.mark.unit

GLSLANG_OUTPUT = """bad.frag
ERROR: bad.frag:3: 'undefined_thing' : undeclared identifier
ERROR: bad.frag:3: '' : compilation terminated
ERROR: 2 compilation errors.  No code generated.


SPIR-V is not generated for failed compile or link
"""

GLSLC_OUTPUT = """bad.frag:3: error: 'undefined_thing' : undeclared identifier
bad.frag:4: error: '' : compilation terminated
2 errors generated.
"""

SPIRV_VAL_OUTPUT = """error: line 2: Result <id> '1' must be less than the ID bound '1'.
  %1 = OpExtInstImport "GLSL.std.450"

"""


def test_glslang_parser_on_real_output() -> None:
    diagnostics = parse_glslang_diagnostics(GLSLANG_OUTPUT)
    assert len(diagnostics) == 2  # the "2 compilation errors" summary is dropped
    first = diagnostics[0]
    assert first.severity is Severity.ERROR
    assert (first.file, first.line) == ("bad.frag", 3)
    assert "undeclared identifier" in first.message


def test_glslang_parser_warnings_and_unlocated_errors() -> None:
    text = "WARNING: shader.frag:7: 'x' : unused\nERROR: Unable to open file\n"
    first, second = parse_glslang_diagnostics(text)
    assert first.severity is Severity.WARNING
    assert first.line == 7
    assert second.severity is Severity.ERROR
    assert second.file is None


def test_glslang_parser_windows_style_path() -> None:
    (diag,) = parse_glslang_diagnostics("ERROR: C:\\work\\a.frag:12: 'x' : bad")
    assert diag.file == "C:\\work\\a.frag"
    assert diag.line == 12


def test_glslc_parser_on_real_output() -> None:
    diagnostics = parse_glslc_diagnostics(GLSLC_OUTPUT)
    assert len(diagnostics) == 2
    assert diagnostics[0].file == "bad.frag"
    assert diagnostics[0].line == 3
    assert diagnostics[0].severity is Severity.ERROR


def test_validator_parser_keeps_instruction_context() -> None:
    (diag,) = parse_validator_diagnostics(SPIRV_VAL_OUTPUT)
    assert diag.severity is Severity.ERROR
    assert "(instruction 2)" in diag.message
    assert "OpExtInstImport" in diag.message
    assert diag.line is None  # instruction index, not a source line


def test_validator_parser_ignores_empty_input() -> None:
    assert parse_validator_diagnostics("") == []


def test_cross_parser_handles_exception_and_error_forms() -> None:
    exception = parse_cross_diagnostics(
        "SPIRV-Cross threw an exception: SPIR-V instruction goes out of bounds."
    )
    assert exception[0].severity is Severity.ERROR
    assert "out of bounds" in exception[0].message
    (error,) = parse_cross_diagnostics("ERROR: something broke")
    assert error.message == "something broke"
    assert parse_cross_diagnostics("") == []


def test_looks_like_spirv() -> None:
    assert looks_like_spirv(b"\x03\x02\x23\x07rest")
    assert looks_like_spirv(b"\x07\x23\x02\x03rest")
    assert not looks_like_spirv(b"#version 450")
    assert not looks_like_spirv(b"")


def test_spirv_tools_env_translation() -> None:
    assert to_spirv_tools_env("spirv1.5") == "spv1.5"
    assert to_spirv_tools_env("vulkan1.1spirv1.4") == "vulkan1.1spv1.4"
    assert to_spirv_tools_env("vulkan1.2") == "vulkan1.2"
    assert to_spirv_tools_env(None) is None
