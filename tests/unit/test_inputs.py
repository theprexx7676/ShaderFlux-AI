"""Tests for input loading and detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import ShaderLanguage, ShaderStage
from shaderflux.source.inputs import (
    decode_text,
    detect_language,
    detect_stage,
    find_entry_candidates,
    load_source,
    parse_language_name,
    parse_stage_name,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("name", "language"),
    [
        ("a.hlsl", ShaderLanguage.HLSL),
        ("a.HLSL", ShaderLanguage.HLSL),
        ("common.hlsli", ShaderLanguage.HLSL),
        ("a.fx", ShaderLanguage.HLSL),
        ("a.glsl", ShaderLanguage.GLSL),
        ("a.vert", ShaderLanguage.GLSL),
        ("a.frag", ShaderLanguage.GLSL),
        ("a.comp", ShaderLanguage.GLSL),
        ("a.spv", ShaderLanguage.SPIRV),
        ("a.txt", None),
        ("noext", None),
    ],
)
def test_detect_language(name: str, language: ShaderLanguage | None) -> None:
    assert detect_language(Path(name)) == language


@pytest.mark.parametrize(
    ("name", "text", "language", "stage"),
    [
        ("a.vert", "", ShaderLanguage.GLSL, ShaderStage.VERTEX),
        ("a.frag", "", ShaderLanguage.GLSL, ShaderStage.FRAGMENT),
        ("a.comp", "", ShaderLanguage.GLSL, ShaderStage.COMPUTE),
        ("light.ps.hlsl", "", ShaderLanguage.HLSL, ShaderStage.FRAGMENT),
        ("light_vs.hlsl", "", ShaderLanguage.HLSL, ShaderStage.VERTEX),
        ("light-cs.hlsl", "", ShaderLanguage.HLSL, ShaderStage.COMPUTE),
        ("x.glsl", "#pragma shader_stage(fragment)", ShaderLanguage.GLSL, ShaderStage.FRAGMENT),
        (
            "x.hlsl",
            '[shader("pixel")] float4 f() : SV_Target {}',
            ShaderLanguage.HLSL,
            ShaderStage.FRAGMENT,
        ),
        ("lighting.hlsl", "", ShaderLanguage.HLSL, None),
        ("ps.hlsl", "", ShaderLanguage.HLSL, None),  # single part: no suffix to read
    ],
)
def test_detect_stage(
    name: str, text: str, language: ShaderLanguage, stage: ShaderStage | None
) -> None:
    assert detect_stage(Path(name), text, language) == stage


def test_detect_stage_without_path() -> None:
    assert detect_stage(None, "", ShaderLanguage.GLSL) is None


@pytest.mark.parametrize(
    ("raw", "stage"),
    [
        ("fragment", ShaderStage.FRAGMENT),
        ("Pixel", ShaderStage.FRAGMENT),
        ("vert", ShaderStage.VERTEX),
        ("tess-control", ShaderStage.TESS_CONTROL),
        ("compute", ShaderStage.COMPUTE),
    ],
)
def test_parse_stage_name(raw: str, stage: ShaderStage) -> None:
    assert parse_stage_name(raw) == stage


def test_parse_names_reject_unknown() -> None:
    with pytest.raises(InvalidInputError):
        parse_stage_name("banana")
    with pytest.raises(InvalidInputError):
        parse_language_name("cobol")
    assert parse_language_name("SPV") is ShaderLanguage.SPIRV
    assert parse_language_name("metal") is ShaderLanguage.MSL


def test_find_entry_candidates() -> None:
    hlsl = (
        "float4 PSMain(float2 uv : TEXCOORD0) : SV_Target { return 0; }\n"
        "[numthreads(8,8,1)] void CSMain(uint3 id : SV_DispatchThreadID) {}\n"
    )
    assert find_entry_candidates(hlsl, ShaderLanguage.HLSL) == ["CSMain", "PSMain"]
    assert find_entry_candidates("void main() {}", ShaderLanguage.GLSL) == ["main"]
    assert find_entry_candidates("float x;", ShaderLanguage.HLSL) == []


def test_decode_text_handles_bom_and_crlf() -> None:
    assert decode_text(b"\xef\xbb\xbfvoid main() {}\r\n") == "void main() {}\r\n"


def test_decode_text_rejects_binary_and_bad_utf8() -> None:
    with pytest.raises(InvalidInputError, match="binary"):
        decode_text(b"\x03\x02\x23\x07\x00\x00")
    with pytest.raises(InvalidInputError, match="UTF-8"):
        decode_text(b"\xff\xfe\xfa")


def test_load_source_detects_everything(tmp_path: Path) -> None:
    path = tmp_path / "tint.frag"
    path.write_text("#version 450\nvoid main() {}\n")
    source = load_source(path, defines={"A": "1"}, include_dirs=[tmp_path])
    assert source.language is ShaderLanguage.GLSL
    assert source.stage is ShaderStage.FRAGMENT
    assert source.entry_point == "main"
    assert source.defines == {"A": "1"}
    assert source.path == path


def test_load_source_explicit_overrides_win(tmp_path: Path) -> None:
    path = tmp_path / "x.txt"
    path.write_text("float4 f() : SV_Target { return 0; }")
    source = load_source(
        path, language=ShaderLanguage.HLSL, stage=ShaderStage.FRAGMENT, entry_point="f"
    )
    assert (source.language, source.stage, source.entry_point) == (
        ShaderLanguage.HLSL,
        ShaderStage.FRAGMENT,
        "f",
    )


def test_load_source_spirv_keeps_bytes(tmp_path: Path) -> None:
    path = tmp_path / "m.spv"
    path.write_bytes(b"\x03\x02\x23\x07rest")
    source = load_source(path)
    assert source.language is ShaderLanguage.SPIRV
    assert source.binary == b"\x03\x02\x23\x07rest"


def test_load_source_errors(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="no such file"):
        load_source(tmp_path / "missing.frag")
    unknown = tmp_path / "x.txt"
    unknown.write_text("hi")
    with pytest.raises(InvalidInputError, match="--from"):
        load_source(unknown)
    big = tmp_path / "big.frag"
    big.write_text("x" * 100)
    with pytest.raises(InvalidInputError, match="limit"):
        load_source(big, max_bytes=10)
