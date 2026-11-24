"""The pre-commit hook definitions other projects will use."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

HOOKS = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
)
BY_ID = {hook["id"]: hook for hook in HOOKS}


def test_the_hooks_exist_and_run_the_installed_command() -> None:
    assert set(BY_ID) == {"shaderflux-lint", "shaderflux-fix-check"}
    assert BY_ID["shaderflux-lint"]["entry"] == "shaderflux lint"
    assert BY_ID["shaderflux-fix-check"]["entry"] == "shaderflux fix --check"
    assert all(hook["language"] == "python" for hook in HOOKS)


@pytest.mark.parametrize(
    "name",
    ["a.hlsl", "dir/b.fx", "c.frag", "d.vert", "e.comp", "f.glsl", "g.mesh", "UPPER.hlsl".lower()],
)
def test_lint_picks_up_shader_sources(name: str) -> None:
    assert re.search(BY_ID["shaderflux-lint"]["files"], name)


@pytest.mark.parametrize(
    "name", ["common.hlsli", "a.spv", "notes.md", "a.hlsl.bak", "frag", "x.py"]
)
def test_lint_ignores_headers_binaries_and_other_files(name: str) -> None:
    assert not re.search(BY_ID["shaderflux-lint"]["files"], name)


def test_fix_check_only_looks_at_hlsl() -> None:
    pattern = BY_ID["shaderflux-fix-check"]["files"]
    assert re.search(pattern, "a.hlsl")
    assert re.search(pattern, "b.fx")
    assert not re.search(pattern, "c.frag")  # fix handles HLSL only
    assert not re.search(pattern, "common.hlsli")


def test_the_file_patterns_cover_every_extension_the_tool_calls_hlsl_or_glsl() -> None:
    from shaderflux.core.models import ShaderLanguage
    from shaderflux.source.inputs import _LANGUAGE_BY_EXTENSION

    pattern = BY_ID["shaderflux-lint"]["files"]
    for ext, language in _LANGUAGE_BY_EXTENSION.items():
        if language in (ShaderLanguage.HLSL, ShaderLanguage.GLSL) and ext != ".hlsli":
            assert re.search(pattern, f"x{ext}"), f"{ext} is a shader source but not hooked"
