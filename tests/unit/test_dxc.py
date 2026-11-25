"""Tests for the DXC backend using a fake ``dxc`` executable.

These verify command construction and diagnostic parsing only. They cannot
prove that real DXC accepts the flags; see ``tests/integration/test_dxc.py``.
"""

from __future__ import annotations

import json
import stat
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import Severity, ShaderLanguage, ShaderSource, ShaderStage, Target
from shaderflux.tools.dxc import (
    BindingPolicy,
    DxcBackend,
    RegisterBinding,
    parse_dxc_diagnostics,
    profile_for,
)

pytestmark = pytest.mark.unit

SPIRV_TARGET = Target(language=ShaderLanguage.SPIRV, environment="vulkan1.2")

FAKE_DXC = textwrap.dedent(
    """\
    #!{python}
    import json, sys, pathlib
    argv = sys.argv[1:]
    pathlib.Path(__file__).with_name("argv.json").write_text(json.dumps(argv))
    source = pathlib.Path(argv[-1]).read_text()
    if "BROKEN" in source:
        sys.stderr.write("{name}:3:12: error: use of undeclared identifier 'undefined_thing'\\n")
        sys.stderr.write("    return undefined_thing;\\n           ^\\n")
        sys.exit(1)
    out = argv[argv.index("-Fo") + 1]
    pathlib.Path(out).write_bytes(b"\\x03\\x02\\x23\\x07FAKE")
    """
)


@pytest.fixture
def fake_dxc(tmp_path: Path) -> Path:
    path = tmp_path / "dxc"
    path.write_text(FAKE_DXC.format(python=sys.executable, name="shader.hlsl"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def argv_of(fake: Path) -> list[str]:
    return json.loads(fake.with_name("argv.json").read_text())


def hlsl(text: str = "float4 main() : SV_Target { return 0; }", **kwargs: object) -> ShaderSource:
    return ShaderSource(
        text=text,
        language=ShaderLanguage.HLSL,
        stage=ShaderStage.FRAGMENT,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.mark.skipif(sys.platform == "win32", reason="fake tool is a shebang script")
class TestWithFakeTool:
    def test_spirv_command_line(self, fake_dxc: Path) -> None:
        backend = DxcBackend(fake_dxc, "1.8")
        source = hlsl(entry_point="PSMain", defines={"A": "1", "B": None})
        result = backend.compile(source, target=SPIRV_TARGET)
        assert result.ok
        assert result.output is not None
        assert result.output.startswith(b"\x03\x02\x23\x07")
        argv = argv_of(fake_dxc)
        assert argv[argv.index("-T") + 1] == "ps_6_0"
        assert argv[argv.index("-E") + 1] == "PSMain"
        assert "-spirv" in argv
        assert "-fspv-target-env=vulkan1.2" in argv
        assert "-DA=1" in argv
        assert "-DB" in argv
        assert argv[-1] == "shader.hlsl"  # relative, so diagnostics do not leak temp paths
        assert result.tool.version == "1.8"

    def test_dxil_check_has_no_spirv_flags(self, fake_dxc: Path) -> None:
        result = DxcBackend(fake_dxc).check_dxil(hlsl())
        assert result.ok
        argv = argv_of(fake_dxc)
        assert "-spirv" not in argv
        assert not any(a.startswith("-fvk") for a in argv)

    def test_error_is_parsed(self, fake_dxc: Path) -> None:
        result = DxcBackend(fake_dxc).compile(hlsl("BROKEN"), target=SPIRV_TARGET)
        assert not result.ok
        assert result.output is None
        (diag,) = result.errors
        assert (diag.line, diag.column) == (3, 12)
        assert "undefined_thing" in diag.message

    def test_binding_policy_is_applied_to_spirv_only(self, fake_dxc: Path) -> None:
        policy = BindingPolicy(shifts={"t": 100, "s": 200})
        backend = DxcBackend(fake_dxc, binding_policy=policy)
        backend.compile(hlsl(), target=SPIRV_TARGET)
        argv = argv_of(fake_dxc)
        i = argv.index("-fvk-t-shift")
        assert argv[i : i + 3] == ["-fvk-t-shift", "100", "all"]
        backend.check_dxil(hlsl())
        assert "-fvk-t-shift" not in argv_of(fake_dxc)


def test_compile_requires_spirv_target(tmp_path: Path) -> None:
    backend = DxcBackend(tmp_path / "dxc")
    with pytest.raises(InvalidInputError):
        backend.compile(hlsl(), target=Target(language=ShaderLanguage.GLSL))


def test_requires_stage_and_hlsl_language(tmp_path: Path) -> None:
    backend = DxcBackend(tmp_path / "dxc")
    with pytest.raises(InvalidInputError, match="stage"):
        backend.build_args(ShaderSource(text="x", language=ShaderLanguage.HLSL), spirv=True)
    with pytest.raises(InvalidInputError, match="HLSL"):
        backend.build_args(
            ShaderSource(text="x", language=ShaderLanguage.GLSL, stage=ShaderStage.VERTEX),
            spirv=True,
        )


@pytest.mark.parametrize(
    "bad",
    [{"A B": "1"}, {"1A": "1"}, {"A": "x\ny"}, {"A;rm": "1"}],
)
def test_rejects_unsafe_defines(tmp_path: Path, bad: dict[str, str]) -> None:
    backend = DxcBackend(tmp_path / "dxc")
    with pytest.raises(InvalidInputError):
        backend.build_args(hlsl(defines=bad), spirv=True)


def test_rejects_unsafe_entry_point_and_environment(tmp_path: Path) -> None:
    backend = DxcBackend(tmp_path / "dxc")
    with pytest.raises(InvalidInputError):
        backend.build_args(hlsl(entry_point="main; rm -rf /"), spirv=True)
    with pytest.raises(InvalidInputError):
        backend.build_args(hlsl(), spirv=True, environment="--evil")


def test_profile_for() -> None:
    assert profile_for(ShaderStage.VERTEX, "6_2") == "vs_6_2"
    assert profile_for(ShaderStage.COMPUTE, "6_0") == "cs_6_0"
    with pytest.raises(InvalidInputError):
        profile_for(ShaderStage.VERTEX, "six")


def test_binding_policy_shift_and_explicit_are_exclusive() -> None:
    with pytest.raises(ValidationError):
        BindingPolicy(
            shifts={"b": 1},
            explicit=[RegisterBinding(reg_type="t", number=0, binding=3)],
        )
    with pytest.raises(ValidationError):
        BindingPolicy(shifts={"b": -1})


def test_binding_policy_args() -> None:
    assert BindingPolicy().to_args() == []
    assert BindingPolicy(shifts={"b": 0, "t": 10}, shift_space=1).to_args() == [
        "-fvk-b-shift", "0", "1", "-fvk-t-shift", "10", "1",
    ]  # fmt: skip
    explicit = BindingPolicy(
        explicit=[RegisterBinding(reg_type="t", number=2, space=1, binding=7, descriptor_set=3)]
    )
    assert explicit.to_args() == ["-fvk-bind-register", "t2", "1", "7", "3"]


def test_parse_dxc_diagnostics_skips_source_context() -> None:
    text = (
        "shader.hlsl:3:12: error: use of undeclared identifier 'x'\n"
        "    return x;\n"
        "           ^\n"
        "shader.hlsl:1:1: warning: unused thing\n"
        "error: validation failed\n"
    )
    first, second, third = parse_dxc_diagnostics(text)
    assert first.severity is Severity.ERROR
    assert (first.file, first.line, first.column) == ("shader.hlsl", 3, 12)
    assert second.severity is Severity.WARNING
    assert third.file is None
    assert third.message == "validation failed"
