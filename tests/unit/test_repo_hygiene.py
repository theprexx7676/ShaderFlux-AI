"""Things that must not be committed to the repository root."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def test_no_compiler_output_is_left_in_the_repository_root() -> None:
    """A hand-run `glslangValidator -V x.frag` writes frag.spv next to you; two of these were
    once committed by `git add -A`. Root-level .gitignore patterns keep them out."""
    stray = sorted(
        p.name for p in ROOT.iterdir() if p.is_file() and p.suffix in {".spv", ".dxil", ".o"}
    )
    assert not stray, f"remove these build outputs from the repository root: {stray}"


def test_gitignore_covers_compiler_output() -> None:
    patterns = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/*.spv" in patterns
