"""Shared fixtures and helpers for the test suite."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

CORPUS = Path(__file__).parent / "corpus"


def require_tool(*names: str) -> None:
    """Skip the current test unless **all** the given tools are on PATH."""
    missing = [name for name in names if not shutil.which(name)]
    if missing:
        pytest.skip(f"missing on PATH: {', '.join(missing)}")


def require_any(*names: str) -> None:
    """Skip the current test unless **at least one** of the given tools is on PATH."""
    if not any(shutil.which(name) for name in names):
        pytest.skip(f"none of {', '.join(names)} found on PATH")


@pytest.fixture
def corpus() -> Path:
    return CORPUS
