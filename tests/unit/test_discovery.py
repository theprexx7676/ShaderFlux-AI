"""Tests for tool discovery, version parsing and the doctor report."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shaderflux.cli.app import app
from shaderflux.tools.discovery import (
    TOOLS,
    ToolSpec,
    ToolState,
    check_tool,
    doctor,
    env_override_name,
    find_executable,
    parse_version,
    read_version,
)

pytestmark = pytest.mark.unit

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX shell scripts")


def make_fake_tool(directory: Path, name: str, output: str, exit_code: int = 0) -> Path:
    path = directory / name
    path.write_text(f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\nexit {exit_code}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_parse_version() -> None:
    assert parse_version("2025.1") == (2025, 1)
    assert parse_version("15.1.0") == (15, 1, 0)
    assert parse_version("v1.8(dev)") == (1, 8)
    assert parse_version("garbage") == ()
    assert parse_version("2025.10") > parse_version("2025.9")


def test_env_override_name() -> None:
    assert env_override_name("spirv-cross") == "SHADERFLUX_SPIRV_CROSS"
    assert env_override_name("dxc") == "SHADERFLUX_DXC"


@POSIX
def test_find_executable_prefers_configured_path(tmp_path: Path) -> None:
    configured = make_fake_tool(tmp_path, "my-dxc", "x")
    other = make_fake_tool(tmp_path, "dxc", "y")
    spec = TOOLS["dxc"]
    found = find_executable(
        spec, configured={"dxc": str(configured)}, environ={"PATH": str(tmp_path)}
    )
    assert found == configured
    assert other.exists()


@POSIX
def test_find_executable_uses_env_override_then_path(tmp_path: Path) -> None:
    override = make_fake_tool(tmp_path, "custom", "x")
    spec = TOOLS["dxc"]
    env = {"PATH": "", "SHADERFLUX_DXC": str(override)}
    assert find_executable(spec, environ=env) == override
    make_fake_tool(tmp_path, "dxc", "x")
    assert find_executable(spec, environ={"PATH": str(tmp_path)}) == tmp_path / "dxc"


@POSIX
def test_find_executable_searches_vulkan_sdk(tmp_path: Path) -> None:
    bin_dir = tmp_path / "sdk" / "bin"
    bin_dir.mkdir(parents=True)
    tool = make_fake_tool(bin_dir, "dxc", "x")
    found = find_executable(TOOLS["dxc"], environ={"PATH": "", "VULKAN_SDK": str(tmp_path / "sdk")})
    assert found == tool


def test_find_executable_missing(tmp_path: Path) -> None:
    assert find_executable(TOOLS["dxc"], environ={"PATH": str(tmp_path)}) is None


@POSIX
@pytest.mark.parametrize(
    ("key", "output", "expected"),
    [
        ("spirv-val", "SPIRV-Tools v2025.1 unknown hash, 2026-05-13T06:03:38+00:00", "2025.1"),
        (
            "glslangValidator",
            "Glslang Version: 11:15.1.0\nESSL Version: OpenGL ES GLSL 3.20",
            "15.1.0",
        ),
        ("glslc", "shaderc 2023.8-1build1\nspirv-tools 2023.6~rc1-2", "2023.8"),
    ],
)
def test_read_version_parses_real_output_formats(
    tmp_path: Path, key: str, output: str, expected: str
) -> None:
    tool = make_fake_tool(tmp_path, key, output)
    assert read_version(TOOLS[key], tool) == expected


@POSIX
def test_read_version_none_when_unparseable_or_no_regex(tmp_path: Path) -> None:
    tool = make_fake_tool(tmp_path, "spirv-val", "no version here")
    assert read_version(TOOLS["spirv-val"], tool) is None
    assert read_version(TOOLS["spirv-cross"], tool) is None


@POSIX
def test_check_tool_states(tmp_path: Path) -> None:
    make_fake_tool(tmp_path, "spirv-val", "SPIRV-Tools v2025.1 x")
    env = {"PATH": str(tmp_path)}
    ok = check_tool(TOOLS["spirv-val"], environ=env)
    assert ok.state is ToolState.OK
    assert ok.version == "2025.1"

    old_spec = ToolSpec(
        key="spirv-val",
        binaries=("spirv-val",),
        purpose="x",
        version_regex=r"SPIRV-Tools v(\d+(?:\.\d+)+)",
        min_version=(2030, 1),
    )
    assert check_tool(old_spec, environ=env).state is ToolState.OLD

    missing = check_tool(TOOLS["dxc"], environ=env, platform="linux")
    assert missing.state is ToolState.MISSING
    assert missing.hint

    make_fake_tool(tmp_path, "spirv-cross", "usage")
    assert check_tool(TOOLS["spirv-cross"], environ=env).state is ToolState.UNKNOWN_VERSION


def test_doctor_with_no_tools_reports_failure(tmp_path: Path) -> None:
    report = doctor(environ={"PATH": str(tmp_path)}, platform="linux")
    assert not report.ok
    missing_required = {t.key for t in report.tools if not t.optional}
    assert missing_required == {"dxc", "spirv-cross", "spirv-val"}
    assert any("GLSL input" in note for note in report.notes)


@POSIX
def test_doctor_ok_when_required_tools_present(tmp_path: Path) -> None:
    make_fake_tool(tmp_path, "dxc", "dxcompiler.so: 1.8(dev)")
    make_fake_tool(tmp_path, "spirv-cross", "usage")
    make_fake_tool(tmp_path, "spirv-val", "SPIRV-Tools v2025.1 x")
    report = doctor(environ={"PATH": str(tmp_path)}, platform="linux")
    assert report.ok


def test_doctor_cli_json_exit_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    for name in list(os.environ):
        if name.startswith("SHADERFLUX_") or name == "VULKAN_SDK":
            monkeypatch.delenv(name)
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert {t["key"] for t in data["tools"]} == set(TOOLS)
