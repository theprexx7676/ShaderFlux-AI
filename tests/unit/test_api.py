"""The public API: it imports, it is documented, and the documented example works."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

import shaderflux.api as api
from shaderflux.api import (
    ShaderLanguage,
    TranslateRequest,
    lint_file,
    lint_text,
    run_translate,
)
from tests.fakes import registry

pytestmark = pytest.mark.unit


def test_everything_listed_in_all_exists_and_nothing_is_missing() -> None:
    for name in api.__all__:
        assert hasattr(api, name), name
    public = {
        name
        for name, value in vars(api).items()
        if not name.startswith("_") and not inspect.ismodule(value) and name != "annotations"
    }
    assert public == set(api.__all__) - {"__version__"}, "export new names in __all__"


def test_importing_the_api_does_not_import_the_command_line_stack() -> None:
    import subprocess
    import sys

    code = "import sys, shaderflux.api; print('typer' in sys.modules or 'rich' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == "False", result.stderr


def test_the_docstring_example_works(tmp_path: Path) -> None:
    shader = tmp_path / "lighting.hlsl"
    shader.write_text(
        "cbuffer C : register(b0) { row_major float4x4 m; };\nTexture2D t : register(t0);\n"
    )
    report = lint_file(shader)
    assert [f.rule for f in report.findings] == ["BND001"]
    assert report.findings[0].format().startswith(f"{shader}:1: error: [BND001]")

    pass_frag = tmp_path / "pass.frag"
    pass_frag.write_text("void main() {}\n")
    outcome = run_translate(
        TranslateRequest(input_file=pass_frag, target_language=ShaderLanguage.HLSL),
        registry=registry(),
    )
    assert outcome.result.ok
    assert outcome.result.output_text == "// hlsl\n"


def test_lint_text_and_rule_lookup() -> None:
    findings = lint_text("float4x4 m;\ncbuffer C { float4x4 n; };", ShaderLanguage.HLSL)
    assert {f.rule for f in findings} == {"MAT002"}
    rule = api.get_rule("MAT002")
    assert rule is not None
    assert rule.id in api.all_rules()


def test_version_is_exposed() -> None:
    assert api.__version__ == importlib.import_module("shaderflux").__version__
