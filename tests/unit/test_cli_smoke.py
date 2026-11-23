"""Smoke tests for the CLI skeleton."""

from __future__ import annotations

import importlib

import pytest
from typer.testing import CliRunner

from shaderflux import __version__
from shaderflux.cli.app import app

pytestmark = pytest.mark.unit

runner = CliRunner()

PACKAGES = ["cli", "core", "tools", "pipeline", "analysis", "llm", "verify", "reporting"]


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


@pytest.mark.parametrize("package", PACKAGES)
def test_subpackages_import(package: str) -> None:
    module = importlib.import_module(f"shaderflux.{package}")
    assert module.__doc__
