"""The Vulkan GLSL rules against the real glslangValidator.

For every snippet in the shared table: if we flag it, glslang must reject it, and if we do not,
glslang must accept it. A disagreement is a bug in a rule (or in our assumption about glslang).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shaderflux.analysis.vulkan_glsl import check_vulkan_glsl
from tests.conftest import require_tool
from tests.vulkan_glsl_cases import CASES

pytestmark = [pytest.mark.integration, pytest.mark.needs_tools]


def glslang_accepts(directory: Path, ext: str, source: str) -> tuple[bool, str]:
    path = directory / f"case.{ext}"
    path.write_text(source)
    run = subprocess.run(
        ["glslangValidator", "-V", path.name, "-o", "out.spv"],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize(("name", "ext", "source", "expected"), CASES, ids=[c[0] for c in CASES])
def test_our_verdict_matches_glslang(
    name: str, ext: str, source: str, expected: frozenset[str], tmp_path: Path
) -> None:
    require_tool("glslangValidator")
    accepted, output = glslang_accepts(tmp_path, ext, source)
    flagged = bool(check_vulkan_glsl(source))
    assert flagged != accepted, (
        f"{name}: we {'flag' if flagged else 'accept'} it but glslang "
        f"{'accepts' if accepted else 'rejects'} it:\n{output}"
    )
