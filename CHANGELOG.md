# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/). Before 1.0, a minor version may change behaviour.

## [Unreleased]

### Added
- CI now runs the HLSL tests against two DXC builds on Linux: the latest release (`v1.9.2609`, reports `1.9(5512-01b62ad4)(1.9.2609.5)`) and the newest release of an older series (`v1.8.2505.1`, whose binary reports `1.9(dev;4950-b106a961)`). Both passed all 20 tests and produced identical output from `scripts/dxc_experiments.py` (binding mapping, matrix packing, SPIRV-Cross re-check). The legs are chosen by `scripts/ci_select_dxc.py`.

## [0.1.0] - 2026-11-25

The first release. Early development: usable today, not yet proven everywhere (see "Known limits").
It is not on PyPI; install it from GitHub, see the README.

### Added
- **`shaderflux lint` and `explain`** for HLSL and GLSL: 16 rules for porting traps (Vulkan binding collisions, matrix conventions, intrinsic differences, GLSL that Vulkan rejects, includes and size limits). Every finding has a confidence level and a concrete fix. Text, JSON or SARIF output; glob patterns work on every platform.
- **`shaderflux fix`** (no AI) for HLSL: inserts `[[vk::binding]]` attributes (BND001) and an explicit `column_major` (MAT002). Insertions only, a diff by default, `--write`, `--out`, `--only`, `--check`, several files and globs, and `--verify` (recompiles with DXC and checks that bindings are distinct; refuses to write a fix that breaks a compiling shader).
- **`shaderflux translate`** between HLSL, GLSL and SPIR-V with DXC, glslang, SPIRV-Cross and SPIRV-Tools: SPIR-V validation, a re-check of the generated GLSL/HLSL, and run reports (`--report`) with an explicit "not checked" list.
- **`shaderflux init`** (starter config, optional GitHub workflow), `doctor` (tool check) and `config show`.
- **GitHub Action** that lints shaders on pull requests and can upload SARIF, **pre-commit hooks** (`shaderflux-lint`, `shaderflux-fix-check`), a public Python API (`shaderflux.api`) and a 10-minute tutorial.
- **Optional, experimental AI repair** (`translate --repair`, `--dry-run`): needs the `ai` extra and the user's own `ANTHROPIC_API_KEY`. A plain install is 14 packages and contains no AI client; `--repair` without the extra explains how to install it and exits 2 before doing any work. `--dry-run` shows exactly what would be sent, and says so when nothing would be.

### What real tools checked
- DXC 1.9 (Linux, in CI): the binding collision and its fix flags, matrix packing defaults and `#pragma pack_matrix`, the output of `fix` (distinct bindings; `column_major` accepted in every form it writes), and that Shader Model 5 HLSL from SPIRV-Cross compiles.
- glslangValidator 15.1.0 and 16.2.0: the Vulkan GLSL rules agree with the compiler on 26 snippets.
- The unit tests run on Linux, macOS and Windows with Python 3.11 to 3.13.

### Known limits
- Windows DXC and DXC versions other than 1.9 are untested; so is `-fvk-use-gl-layout`.
- `translate --repair` has never run against the live API (no key was available); it is tested with a scripted model.
- The Action's upload to code scanning has never run (CI skips it; it needs repository permissions).
- Not built: image comparison, batch mode and permutations; `fix` handles only BND001 and MAT002.
- Lint rules are token-based heuristics, not a compiler front end; their accuracy on the bundled corpus is a regression guard, not independent evidence.
