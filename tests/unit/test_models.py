"""Tests for the core domain models."""

from __future__ import annotations

import pytest

from shaderflux.core.models import (
    Diagnostic,
    Severity,
    ShaderLanguage,
    ShaderSource,
    ShaderStage,
    StageResult,
    ToolInfo,
    TranslationResult,
)

pytestmark = pytest.mark.unit


def make_source(**overrides: object) -> ShaderSource:
    values: dict[str, object] = {
        "text": "void main() {}",
        "language": ShaderLanguage.GLSL,
        "stage": ShaderStage.FRAGMENT,
    }
    values.update(overrides)
    return ShaderSource(**values)  # type: ignore[arg-type]


def test_content_hash_is_stable_and_order_independent() -> None:
    a = make_source(defines={"A": "1", "B": None})
    b = make_source(defines={"B": None, "A": "1"})
    assert a.content_hash == b.content_hash
    assert len(a.content_hash) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"text": "void main() { }"},
        {"stage": ShaderStage.VERTEX},
        {"entry_point": "other"},
        {"defines": {"X": "1"}},
        {"language": ShaderLanguage.HLSL},
    ],
)
def test_content_hash_changes_with_inputs(change: dict[str, object]) -> None:
    assert make_source().content_hash != make_source(**change).content_hash


def test_hash_ignores_path() -> None:
    from pathlib import Path

    assert make_source(path=Path("a.frag")).content_hash == make_source().content_hash


def test_diagnostic_format() -> None:
    located = Diagnostic(severity=Severity.ERROR, message="bad", file="a.frag", line=3, column=7)
    assert located.format() == "a.frag:3:7: error: bad"
    assert Diagnostic(severity=Severity.WARNING, message="hm", file="a.frag", line=2).format() == (
        "a.frag:2: warning: hm"
    )
    assert Diagnostic(severity=Severity.NOTE, message="fyi").format() == "note: fyi"


def test_translation_result_json_round_trip() -> None:
    diag = Diagnostic(severity=Severity.ERROR, message="bad", file="a.frag", line=3, tool="glslc")
    result = TranslationResult(
        ok=False,
        stages=[
            StageResult(
                name="compile",
                ok=False,
                tool=ToolInfo(name="glslc", version="2023.8"),
                command=["glslc", "a.frag"],
                duration_s=0.1,
                diagnostics=[diag],
            )
        ],
    )
    restored = TranslationResult.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.diagnostics == [diag]
