# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project aims to follow [Semantic Versioning](https://semver.org/) once released.

## [Unreleased]

### Added
- Project README and detailed work plan (`docs/PLAN.md`).
- Repository foundation: license, packaging, tooling, CI, templates and contributor docs.
- `shaderflux --version` CLI skeleton with smoke tests.
- `shaderflux doctor` to check external tools (text and `--json`).
- Safe subprocess runner, tool discovery and backends for glslangValidator, glslc, SPIRV-Cross and SPIRV-Tools, tested against the real tools.
- DXC backend (unverified against a real `dxc` so far).
- Core domain models and typed errors.
- Configuration loading (`shaderflux.toml`, user file, environment, CLI) and `shaderflux config show`.
- Input detection, `#include` graph with path-traversal guard, route planner, translation cache and atomic output writing.
- `shaderflux translate` using the deterministic tool chain (no LLM). Tested end to end for GLSL input.
