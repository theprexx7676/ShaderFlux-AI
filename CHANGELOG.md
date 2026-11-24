# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project aims to follow [Semantic Versioning](https://semver.org/) once released.

## [Unreleased]

### Changed (works without any API)
- The project no longer leans on an LLM: everything useful runs with no API key, account or network. The AI repair (`translate --repair`) is documented and labelled as optional and experimental, uses only the user's own key, and has never run against the live API.

### Fixed (found in review of a CI log)
- `translate --repair --dry-run` built a prompt and said "this is exactly what would be sent" even when the failure was a missing tool, where a real `--repair` sends nothing. It now says `nothing would be sent: ...` (exit 1) using the same rule as the real repair loop.

### Changed (lighter install)
- The Anthropic SDK is now an optional extra (`pip install "shaderflux[ai]"`) and is imported only when `--repair` actually runs. A plain install is 14 packages (25 with the extra, measured from the built wheel). Without the extra, `translate --repair` says how to install it and exits 2 before doing any work; `--repair --dry-run`, `lint`, `fix`, `init` and `translate` are unaffected. A new CI job (`lean-install`) installs the package with no extras and checks this.

### Added
- Pre-commit hooks (`.pre-commit-hooks.yaml`): `shaderflux-lint` and `shaderflux-fix-check`, run for real with pre-commit.
- Lint rules `VKG001` to `VKG004` for GLSL going to Vulkan: `gl_VertexID` / `gl_InstanceID`, uniforms outside a block, samplers or images without a binding, inputs and outputs without a location. Each comes with the replacement to write. Checked against glslangValidator 15.1.0 and 16.2.0 on 26 snippets (both agree on all) and on the corpus.
- `shaderflux init` writes a starter `shaderflux.toml` and, with `--github`, a workflow that lints shaders on pull requests. It never overwrites files without `--force` and checks everything before writing. New public API `run_init`.
- `docs/tutorial-first-port.md`: a 10-minute walkthrough with real output.
- `shaderflux fix` accepts several files and glob patterns (`--check` over a whole tree for CI).
- `shaderflux fix` (no AI): inserts `[[vk::binding]]` attributes for colliding bindings (BND001) and an explicit `column_major` for unqualified constant-buffer matrices (MAT002). Insertions only, diff by default, `--write`, `--out`, `--only`, `--check`, and `--verify` (recompiles with DXC, checks that bindings are distinct, and refuses to write a fix that breaks a compiling shader); withheld for BND001 when the shader includes other files. New public API `run_fix`.

### Fixed (found by running a real DXC in CI)
- Translating to HLSL without `--hlsl-model` produced Shader Model 3 HLSL (`sampler2D`, `tex2D`), which DXC rejects. The default is now Shader Model 5.0.
- A new `dxc-tests` CI job downloads DXC and exercises the HLSL path; it confirmed the binding-collision rule and its fix flags, and settled that DXC packs unqualified matrices column-major.

### Changed (structure)
- The code is a one-way stack of packages, checked by a test: `core` < `source`, `tools` < `verify`, `analysis` < `pipeline` < `llm` < `reporting` < `workflows` < `cli`. The documented layering had been wrong.
- New `source` package (inputs, includes, glob patterns) so `analysis` no longer depends on `pipeline`.
- New `workflows` package: the translate logic moved out of the CLI; the command is now options in, output out.
- `tools/base.py` split into `base`, `validation` and `registry`; `cli/doctor.py` renamed to `doctor_cmd.py`.
- New public Python API, `shaderflux.api`, and `python -m shaderflux`.

### Fixed (CI findings)
- The GitHub Action script failed on macOS (bash 3.2 has no `globstar`). `shaderflux lint` now expands glob patterns itself, including `**`, so Windows and macOS behave like Linux.

### Fixed (review pass)
- `lint` could hang for minutes on a crafted file (regex backtracking) and was quadratic on large files; now linear, with size and line-length limits (rule `LNT001`).
- File names starting with `-` were interpreted as compiler options.
- Child processes no longer inherit environment variables that look like secrets.
- `translate` now checks `--out`, `--write-fixed` and `--report` and option combinations before doing any work or LLM call.
- README claims that were stale or too strong were corrected.

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
- `shaderflux lint` and `shaderflux explain` (binding, matrix and intrinsic rules; JSON and SARIF output).
- Output re-check: the generated GLSL/HLSL is compiled again (`--recheck`, on by default). Found that GLSL generated without `--vulkan` may not compile as Vulkan GLSL.
- GitHub Action (`action.yml`) that runs `lint` on pull requests and can upload SARIF to code scanning. The script is tested and CI runs the Action itself on this repository's shaders; the SARIF upload step has not been exercised.
- Run reports (`translate --report FILE`, Markdown or JSON) with a verdict and an explicit "not checked" list.
- LLM repair: `translate --repair` with provider interface, versioned prompts, safe patch application, repair loop and `--dry-run`. Tested offline; not yet run against the live API.
