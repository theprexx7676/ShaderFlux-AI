"""Create starter files for a project: the workflow behind ``shaderflux init``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from shaderflux.core.config import PROJECT_FILE
from shaderflux.core.errors import InvalidInputError
from shaderflux.pipeline.output import write_bytes_atomic

WORKFLOW_PATH = Path(".github") / "workflows" / "lint-shaders.yml"
_SAFE_DIR = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")

CONFIG_TEMPLATE = """\
# ShaderFlux-AI settings for this project. Every line is optional.
# See what is in effect, and where each value comes from: shaderflux config show
# No API key ever goes in here (it is read only from ANTHROPIC_API_KEY, and only
# if you choose to use the optional, experimental `translate --repair`).

# Vulkan environment used when compiling to SPIR-V.
default_environment = "vulkan1.2"

# Directories searched for #include files, like -I on the command line.
include_dirs = [{include_dirs}]

# Point at specific tool binaries if they are not on your PATH.
# [tools]
# dxc = "C:/VulkanSDK/Bin/dxc.exe"
"""

WORKFLOW_TEMPLATE = """\
# Written by `shaderflux init`. Checks shaders for known porting traps on pull requests.
name: Lint shaders

on:
  pull_request:
    paths: ["{directory}/**"]

permissions:
  contents: read
  security-events: write # only needed for upload-sarif

jobs:
  shaderflux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: theprexx7676/ShaderFlux-AI@v0.1.0 # a release tag; update it to upgrade
        with:
          paths: "{directory}/**/*.hlsl {directory}/**/*.glsl"
          fail-on: error
          upload-sarif: "true"
"""


@dataclass
class InitRequest:
    directory: Path = Path(".")  # the project root to write into
    shaders_dir: str = "shaders"  # where the shaders live, relative to the root
    github: bool = False  # also write the GitHub Actions workflow
    force: bool = False


@dataclass
class InitOutcome:
    written: list[Path] = field(default_factory=list)


def _check_shaders_dir(name: str) -> str:
    cleaned = name.strip().rstrip("/")
    if not _SAFE_DIR.match(cleaned) or ".." in cleaned.split("/"):
        raise InvalidInputError(
            f"invalid shader directory {name!r}: use a relative path of letters, digits, "
            "'_', '-', '.' and '/'"
        )
    return cleaned


def render_files(request: InitRequest) -> dict[Path, str]:
    shaders = _check_shaders_dir(request.shaders_dir)
    files = {Path(PROJECT_FILE): CONFIG_TEMPLATE.format(include_dirs=f'"{shaders}/common"')}
    if request.github:
        files[WORKFLOW_PATH] = WORKFLOW_TEMPLATE.format(directory=shaders)
    return files


def run_init(request: InitRequest) -> InitOutcome:
    """Write the starter files. Refuses to overwrite anything unless ``force``; checks first."""
    root = Path(request.directory)
    if root.exists() and not root.is_dir():
        raise InvalidInputError(f"{root} is not a directory")
    files = render_files(request)  # validates the options before anything is written
    targets = {root / relative: text for relative, text in files.items()}
    clashes = [str(p) for p in targets if p.exists() and not request.force]
    if clashes:
        raise InvalidInputError(f"already exists: {', '.join(clashes)} (use --force to overwrite)")
    outcome = InitOutcome()
    for path, text in targets.items():
        write_bytes_atomic(path, text.encode("utf-8"))
        outcome.written.append(path)
    return outcome
