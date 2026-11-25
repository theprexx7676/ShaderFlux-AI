"""Finding external tools and reading their versions."""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from shaderflux.core.errors import ShaderFluxError
from shaderflux.tools.runner import run_tool

VERSION_TIMEOUT_S = 15.0


@dataclass(frozen=True)
class ToolSpec:
    """Static description of an external tool."""

    key: str
    binaries: tuple[str, ...]
    purpose: str
    version_args: tuple[str, ...] = ("--version",)
    version_regex: str | None = None
    min_version: tuple[int, ...] | None = None
    optional: bool = False
    install_hints: Mapping[str, str] = field(default_factory=dict)


_VULKAN_SDK = "Install the Vulkan SDK (https://vulkan.lunarg.com/) or your package manager."

_SPIRV_TOOLS_HINTS = {"linux": "apt install spirv-tools", "darwin": "brew install spirv-tools"}

TOOLS: dict[str, ToolSpec] = {
    spec.key: spec
    for spec in (
        ToolSpec(
            key="dxc",
            binaries=("dxc",),
            purpose="HLSL to DXIL / SPIR-V compiler",
            # VERIFY: format of `dxc --version` was not checked against a real binary here.
            version_regex=r"(\d+\.\d+(?:\.\d+)?)",
            install_hints={
                "linux": _VULKAN_SDK + " The distro package may be missing or old.",
                "darwin": _VULKAN_SDK + " Or: brew install directx-shader-compiler",
                "win32": _VULKAN_SDK + " It includes dxc.exe.",
            },
        ),
        ToolSpec(
            key="spirv-cross",
            binaries=("spirv-cross",),
            purpose="SPIR-V to GLSL / HLSL / MSL cross-compiler and reflection",
            # Some builds have no --version flag, so the version may be unknown.
            version_regex=None,
            install_hints={
                "linux": "apt install spirv-cross (can be very old) or build from source.",
                "darwin": "brew install spirv-cross",
                "win32": _VULKAN_SDK,
            },
        ),
        ToolSpec(
            key="spirv-val",
            binaries=("spirv-val",),
            purpose="SPIR-V validator",
            version_regex=r"SPIRV-Tools v(\d+(?:\.\d+)+)",
            install_hints={
                "linux": "apt install spirv-tools",
                "darwin": "brew install spirv-tools",
                "win32": _VULKAN_SDK,
            },
        ),
        ToolSpec(
            key="spirv-opt",
            binaries=("spirv-opt",),
            purpose="SPIR-V optimiser (optional)",
            version_regex=r"SPIRV-Tools v(\d+(?:\.\d+)+)",
            optional=True,
            install_hints={
                "linux": "apt install spirv-tools",
                "darwin": "brew install spirv-tools",
            },
        ),
        ToolSpec(
            key="spirv-dis",
            binaries=("spirv-dis",),
            purpose="SPIR-V disassembler (used for readable diffs)",
            version_regex=r"SPIRV-Tools v(\d+(?:\.\d+)+)",
            optional=True,
            install_hints={
                "linux": "apt install spirv-tools",
                "darwin": "brew install spirv-tools",
            },
        ),
        ToolSpec(
            key="glslangValidator",
            binaries=("glslangValidator", "glslang"),
            purpose="GLSL to SPIR-V compiler (this or glslc is needed for GLSL input)",
            version_regex=r"Glslang Version:\s*(?:\d+:)?(\d+\.\d+\.\d+)",
            optional=True,
            install_hints={
                "linux": "apt install glslang-tools",
                "darwin": "brew install glslang",
                "win32": _VULKAN_SDK,
            },
        ),
        ToolSpec(
            key="glslc",
            binaries=("glslc",),
            purpose="GLSL to SPIR-V compiler from shaderc (alternative to glslangValidator)",
            version_regex=r"shaderc\s+v?(\d{4}\.\d+)",
            optional=True,
            install_hints={
                "linux": "apt install glslc",
                "darwin": "brew install shaderc",
                "win32": _VULKAN_SDK,
            },
        ),
    )
}

_GLSL_FRONTENDS = ("glslangValidator", "glslc")


class ToolState(StrEnum):
    OK = "ok"
    MISSING = "missing"
    OLD = "old"
    UNKNOWN_VERSION = "unknown_version"


class ToolStatus(BaseModel):
    key: str
    purpose: str
    optional: bool
    state: ToolState
    path: str | None = None
    version: str | None = None
    hint: str | None = None


class DoctorReport(BaseModel):
    ok: bool
    platform: str
    tools: list[ToolStatus]
    notes: list[str]


def parse_version(text: str) -> tuple[int, ...]:
    """Turn ``"2025.1"`` into ``(2025, 1)``. Non-numeric parts are ignored."""
    return tuple(int(part) for part in re.findall(r"\d+", text))


def env_override_name(key: str) -> str:
    return "SHADERFLUX_" + re.sub(r"[^A-Za-z0-9]", "_", key).upper()


def find_executable(
    spec: ToolSpec,
    *,
    configured: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Locate a tool.

    Order: explicit configuration, ``SHADERFLUX_<TOOL>`` environment variable,
    ``PATH``, then ``$VULKAN_SDK/bin``.
    """
    environ = os.environ if environ is None else environ
    candidates: list[str] = []
    if configured and spec.key in configured:
        candidates.append(configured[spec.key])
    override = environ.get(env_override_name(spec.key))
    if override:
        candidates.append(override)
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path
        found = shutil.which(candidate)
        if found:
            return Path(found)

    for binary in spec.binaries:
        found = shutil.which(binary, path=environ.get("PATH"))
        if found:
            return Path(found)

    sdk = environ.get("VULKAN_SDK")
    if sdk:
        for sub in ("bin", "Bin", "x86_64/bin"):
            for binary in spec.binaries:
                found = shutil.which(binary, path=str(Path(sdk) / sub))
                if found:
                    return Path(found)
    return None


def read_version(spec: ToolSpec, path: Path) -> str | None:
    """Ask a tool for its version. Returns ``None`` if it cannot be determined."""
    if spec.version_regex is None:
        return None
    try:
        run = run_tool([path, *spec.version_args], timeout=VERSION_TIMEOUT_S)
    except ShaderFluxError:
        return None
    match = re.search(spec.version_regex, run.stdout_text + "\n" + run.stderr_text)
    return match.group(1) if match else None


def install_hint(spec: ToolSpec, platform: str | None = None) -> str | None:
    platform = platform or sys.platform
    key = "linux" if platform.startswith("linux") else platform
    return spec.install_hints.get(key)


def check_tool(
    spec: ToolSpec,
    *,
    configured: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> ToolStatus:
    path = find_executable(spec, configured=configured, environ=environ)
    base = {"key": spec.key, "purpose": spec.purpose, "optional": spec.optional}
    if path is None:
        return ToolStatus(**base, state=ToolState.MISSING, hint=install_hint(spec, platform))
    version = read_version(spec, path)
    if version is None:
        return ToolStatus(**base, state=ToolState.UNKNOWN_VERSION, path=str(path))
    if spec.min_version is not None and parse_version(version) < spec.min_version:
        wanted = ".".join(map(str, spec.min_version))
        return ToolStatus(
            **base,
            state=ToolState.OLD,
            path=str(path),
            version=version,
            hint=f"version {wanted} or newer is required",
        )
    return ToolStatus(**base, state=ToolState.OK, path=str(path), version=version)


def doctor(
    *,
    configured: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    keys: Sequence[str] | None = None,
) -> DoctorReport:
    """Check every known tool and summarise what is usable."""
    specs = [TOOLS[k] for k in keys] if keys else list(TOOLS.values())
    statuses = [
        check_tool(spec, configured=configured, environ=environ, platform=platform)
        for spec in specs
    ]
    notes: list[str] = []
    by_key = {s.key: s for s in statuses}

    if all(k in by_key for k in _GLSL_FRONTENDS) and all(
        by_key[k].state is ToolState.MISSING for k in _GLSL_FRONTENDS
    ):
        notes.append("GLSL input needs glslangValidator or glslc, and neither was found.")
    for status in statuses:
        if status.state is ToolState.UNKNOWN_VERSION:
            notes.append(f"{status.key}: found, but its version could not be determined.")

    blocking = [
        s for s in statuses if not s.optional and s.state in (ToolState.MISSING, ToolState.OLD)
    ]
    return DoctorReport(
        ok=not blocking,
        platform=platform or sys.platform,
        tools=statuses,
        notes=notes,
    )
