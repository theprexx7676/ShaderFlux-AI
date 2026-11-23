# ShaderFlux-AI: Detailed Work Plan

Status: **draft for review**. Nothing here is implemented yet.

How to read this document:
- Phases are ordered by dependency. Each task has micro-steps as checkboxes and an **Acceptance** line that says when it is done.
- IDs (for example `3.2.4`) are stable, so issues and commits can refer to them.
- Anything marked **VERIFY** is a fact I could not confirm from the sources I found. The step must check it (tool help output, docs, or a tiny experiment) before relying on it.
- Anything marked **DECISION** needs your approval before work starts.

---

## 0. Ground rules

### 0.1 Product statement
An open-source assistant that helps developers port shaders to PC. A deterministic compiler chain does the mechanical work. An LLM handles judgment calls. Real compilers and validators verify every result.

### 0.2 Principles
1. **Tools first, LLM second.** Never ask the LLM to do what DXC, SPIRV-Cross or a lint rule can do exactly.
2. **Nothing is "done" until verified.** Output is labelled `verified`, `partially verified` or `unverified`.
3. **Small, reviewable changes.** The LLM proposes diffs, not whole-file rewrites, wherever possible.
4. **Reproducible.** Every report records tool versions, model name, prompts' version, and input hashes.
5. **Works offline.** The deterministic pipeline must run with no network and no API key.
6. **Privacy by default.** No shader leaves the machine unless the user enabled LLM features and configured a key.
7. **No proprietary content.** No console SDK code, headers or shaders in the repo, tests or prompts.
8. **Honest scope.** Do not claim "exact rendering output". Claim "verified within stated checks".

### 0.3 Decisions to confirm (DECISION)
| # | Decision | My default | Alternatives |
| --- | --- | --- | --- |
| D1 | Implementation language | Python 3.11+ | Rust, C++ |
| D2 | LLM provider | Claude via the Anthropic SDK, behind an interface | Multi-provider from day one |
| D3 | Primary first direction | HLSL to SPIR-V/GLSL | GLSL to HLSL |
| D4 | CLI framework | Typer | argparse, Click |
| D5 | Data models | Pydantic v2 | dataclasses |
| D6 | Build backend and env tool | hatchling + uv | setuptools, poetry |
| D7 | Copyright holder name for LICENSE | (needed from you) | n/a |
| D8 | Distribution | PyPI package + Docker image with tools preinstalled | PyPI only |
| D9 | Project name on PyPI | `shaderflux` (check availability) | `shaderflux-ai` |

### 0.4 Corrections from my earlier answers (self-check)
These are things I said before that need fixing or a caveat:
- **Broken link.** One link in my earlier message to the Vulkan Guide HLSL page contained a stray hidden character. The correct URL is `https://github.com/KhronosGroup/Vulkan-Guide/blob/master/chapters/hlsl.adoc`.
- **Tool health is unconfirmed.** I implied ShaderConductor and SPIRV-Cross are safe long-term foundations. My checks could not confirm current maintenance status for either. Consequence: tool backends are pluggable, versions are pinned, and Phase 2 includes a maintenance-status check (last release, open issues) before committing.
- **Slang license.** Sources disagreed (Apache 2.0 with LLVM exception vs MIT). **VERIFY** in the Slang repository's LICENSE file before bundling or linking anything.
- **Matrix conventions.** The sources I found describe "row-major vs column-major" inconsistently, because storage order and math convention are different things and are often mixed up. Task 4.3.1 builds a verified convention table from experiments instead of from memory.
- **README roadmap.** The old README ticked "local prototyping" but the repository contained no code. I changed that item to "Project idea and scope".
- **Software rasterizer.** Lavapipe describes itself as non-conformant and for testing use only. Image comparison is therefore a regression aid, not proof. SwiftShader is an alternative worth evaluating.
- **Binding flags.** DXC's `-fvk-*-shift` options and the exact argument form must be checked against `dxc --help`. The two-argument `<N> <space>` form I saw came from Slang's documentation.
- **Structured outputs.** Anthropic's structured-output feature appeared as both beta and generally available in different pages. **VERIFY** the current state in the official docs before coding against it.
- **PSSL and console dialects.** I found no public documentation, which is expected because of NDAs. The plan does not depend on it.

---

## Phase 1: Repository foundation

Goal: a clean, buildable, tested, documented empty project that other phases can build on.

### 1.1 Legal and project files
- [ ] 1.1.1 Add `LICENSE` (MIT) once D7 gives the copyright holder.
- [ ] 1.1.2 Add `NOTICE`/`THIRD_PARTY.md` listing external tools (DXC, SPIRV-Cross, SPIRV-Tools, glslang) with their licenses. **VERIFY** each license from its repository.
- [ ] 1.1.3 Add `CODE_OF_CONDUCT.md` (Contributor Covenant).
- [ ] 1.1.4 Add `SECURITY.md` (how to report vulnerabilities, supported versions).
- [ ] 1.1.5 Add `CONTRIBUTING.md` (setup, test commands, commit style, how to add a test shader).
- [ ] 1.1.6 Add `CHANGELOG.md` using Keep a Changelog format.
- [ ] 1.1.7 Add `.gitignore` (Python, build outputs, caches, `.env`, `*.spv` outputs in scratch dirs).
- [ ] 1.1.8 Add `.editorconfig`.
- **Acceptance:** files exist, README links resolve, license matches README.

### 1.2 Python packaging
- [ ] 1.2.1 Create `pyproject.toml` with project metadata, Python `>=3.11`, entry point `shaderflux`.
- [ ] 1.2.2 Choose layout: `src/shaderflux/` with `__init__.py` and `py.typed`.
- [ ] 1.2.3 Declare dependencies: `typer`, `pydantic`, `rich`, `anthropic`, `tomli-w` (if config is written), `platformdirs`.
- [ ] 1.2.4 Declare dev dependencies: `pytest`, `pytest-cov`, `ruff`, `mypy` (or `pyright`), `pre-commit`, `hypothesis` (optional).
- [ ] 1.2.5 Add `shaderflux --version` reading from package metadata.
- [ ] 1.2.6 Verify `uv sync` (or chosen tool) and `pip install -e .` both work in a clean venv.
- **Acceptance:** fresh clone to working `shaderflux --version` in under 5 commands.

### 1.3 Quality tooling
- [ ] 1.3.1 Configure ruff (lint + format) in `pyproject.toml`.
- [ ] 1.3.2 Configure type checking in strict mode for `src/`.
- [ ] 1.3.3 Configure pytest: test paths, markers (`unit`, `integration`, `needs_tools`, `needs_llm`, `needs_gpu`), default to skipping the last three.
- [ ] 1.3.4 Add `pre-commit` config (ruff, trailing whitespace, end-of-file, large-file check).
- [ ] 1.3.5 Add a `Makefile` or `justfile` with `setup`, `lint`, `type`, `test`, `test-all`.
- **Acceptance:** `make lint type test` passes on the empty skeleton.

### 1.4 Continuous integration
- [ ] 1.4.1 GitHub Actions workflow: lint, type check, unit tests on Python 3.11, 3.12, 3.13.
- [ ] 1.4.2 Matrix over `ubuntu-latest`, `windows-latest`, `macos-latest` for unit tests (shader tools tests only on Linux at first).
- [ ] 1.4.3 Second workflow: integration tests with shader tools installed (see 2.1 for how tools are obtained). Runs on push to main and on PRs touching `src/` or `tests/`.
- [ ] 1.4.4 Cache pip and tool downloads.
- [ ] 1.4.5 Upload coverage and test artifacts.
- [ ] 1.4.6 Add a scheduled weekly job that runs the integration suite against the latest tool versions, so tool drift is detected early.
- [ ] 1.4.7 Add Dependabot (or Renovate) for Python deps and GitHub Actions.
- [ ] 1.4.8 Add status badges to the README only after the workflows are green.
- **Acceptance:** green CI on a PR that only adds the skeleton.

### 1.5 Repository templates
- [ ] 1.5.1 Issue templates: bug report (with `shaderflux doctor` output field), porting problem report, feature request.
- [ ] 1.5.2 Pull request template (what, why, tests, docs).
- [ ] 1.5.3 Labels: `good first issue`, `needs-repro`, `shader-corpus`, `llm`, `tooling`, `docs`.
- **Acceptance:** templates appear in the GitHub UI.

### 1.6 Directory skeleton
```
src/shaderflux/
  cli/            command definitions
  core/           models, config, errors, logging
  tools/          external tool backends (dxc, spirv_cross, ...)
  pipeline/       routing, includes, orchestration
  analysis/       reflection, bindings, lint rules
  llm/            provider interface, prompts, repair loop
  verify/         compile checks, reflection diff, image diff
  reporting/      report models and renderers
tests/
  unit/  integration/  corpus/
docs/
  PLAN.md  architecture.md  guides/
examples/
```
- [ ] 1.6.1 Create empty packages with docstrings stating each package's responsibility.
- [ ] 1.6.2 Add `docs/architecture.md` with the pipeline diagram from the README and the package responsibilities.
- **Acceptance:** `import shaderflux.<pkg>` works for every package.

---

## Phase 2: External tool layer

Goal: reliable, testable access to the compilers and validators, with clear errors when they are missing.

### 2.1 Tool inventory and acquisition
- [ ] 2.1.1 List tools to support: `dxc`, `spirv-cross`, `spirv-val`, `spirv-opt`, `spirv-dis`, `spirv-as`, `glslangValidator` and/or `glslc`. Optional later: `slangc`, `naga`, `tint`.
- [ ] 2.1.2 For each tool record: purpose, license (**VERIFY**), how users install it (package manager, Vulkan SDK, release binary), and the minimum version we test against.
- [ ] 2.1.3 Check maintenance status for each (last release date, recent commits, open critical issues). Record the result in `docs/tools.md`. This resolves the unconfirmed claims in 0.4.
- [ ] 2.1.4 Decide how CI gets the tools: Vulkan SDK download, distro packages, or release binaries from the projects' GitHub releases. Pin versions and checksums.
- [ ] 2.1.5 Write `scripts/install_tools_ci.sh` for Linux and equivalents for Windows and macOS only if needed.
- **Acceptance:** CI can run `dxc --version` and `spirv-cross --help` on Linux.

### 2.2 Subprocess runner
- [ ] 2.2.1 Implement `run_tool(args, input=None, timeout, cwd, env)` returning `ToolRun(returncode, stdout, stderr, duration, command)`.
- [ ] 2.2.2 Never use `shell=True`. Pass argument lists only. Reject paths containing NUL.
- [ ] 2.2.3 Enforce a timeout and kill the whole process group on timeout.
- [ ] 2.2.4 Cap captured output size to avoid memory blowups from runaway tools.
- [ ] 2.2.5 Run in a fresh temp directory per invocation. Clean it up on success and optionally keep it with `--keep-temp`.
- [ ] 2.2.6 Redact home directory and API-key-like strings from stored command lines.
- [ ] 2.2.7 Unit tests with a fake executable (small Python script) for: success, non-zero exit, timeout, huge output, missing binary.
- **Acceptance:** all failure modes produce typed errors, never hangs or tracebacks.

### 2.3 Tool discovery and `doctor`
- [ ] 2.3.1 Discover tools via config path, then `PATH`, then well-known locations (`VULKAN_SDK`).
- [ ] 2.3.2 Query each tool's version and parse it into a comparable structure.
- [ ] 2.3.3 Compare with the tested range. Warn on untested versions. Error below the minimum.
- [ ] 2.3.4 Implement `shaderflux doctor` printing a table: tool, path, version, status, install hint per OS.
- [ ] 2.3.5 Add `--json` output for bug reports.
- [ ] 2.3.6 Unit tests with mocked version outputs.
- **Acceptance:** on a machine with no tools, `doctor` lists each missing tool with an install hint and exits non-zero.

### 2.4 Backend interfaces
- [ ] 2.4.1 Define `CompilerBackend` protocol: `compile(source, stage, entry, defines, includes, target) -> CompileResult`.
- [ ] 2.4.2 Define `CrossCompilerBackend`: `convert(spirv, target_lang, options) -> ConvertResult`.
- [ ] 2.4.3 Define `ValidatorBackend`: `validate(spirv, env) -> list[Diagnostic]`.
- [ ] 2.4.4 `CompileResult` carries output bytes/text, diagnostics, tool name, version, exact command.
- [ ] 2.4.5 Registry so a backend can be swapped or added without touching the pipeline.
- **Acceptance:** a fake backend can be registered in tests and used by the pipeline.

### 2.5 DXC backend
- [ ] 2.5.1 HLSL to DXIL compile (for "does this compile for D3D12" checks).
- [ ] 2.5.2 HLSL to SPIR-V compile with `-spirv` and a configurable target environment (for example Vulkan 1.2). **VERIFY** flag names with `dxc --help`.
- [ ] 2.5.3 Pass entry point, stage profile (`vs_6_x`, `ps_6_x`, `cs_6_x`...), defines, include dirs.
- [ ] 2.5.4 Map binding options (`-fvk-b-shift`, `-fvk-t-shift`, `-fvk-s-shift`, `-fvk-u-shift`, `-fvk-bind-register`) from our own `BindingPolicy` model. **VERIFY** exact syntax and the note that shift and bind-register options cannot be combined.
- [ ] 2.5.5 Support `[[vk::binding]]` attribute inspection (read, not rewrite) for later analysis.
- [ ] 2.5.6 Parse DXC diagnostics (file, line, column, severity, message) into `Diagnostic`.
- [ ] 2.5.7 Golden tests: five tiny shaders (vertex passthrough, textured pixel, constant buffer, compute with UAV, one that fails to compile).
- **Acceptance:** each golden shader compiles or fails as expected, with parsed diagnostics.

### 2.6 SPIRV-Cross backend
- [ ] 2.6.1 SPIR-V to GLSL with version and Vulkan-semantics options.
- [ ] 2.6.2 SPIR-V to HLSL with shader model option.
- [ ] 2.6.3 SPIR-V to MSL (kept optional, not in first release scope).
- [ ] 2.6.4 SPIR-V reflection output (JSON) for the analysis phase.
- [ ] 2.6.5 Parse tool errors into diagnostics.
- [ ] 2.6.6 Golden tests converting the DXC outputs from 2.5.7.
- **Acceptance:** converted GLSL from golden SPIR-V compiles with glslang (2.8).

### 2.7 SPIRV-Tools backend
- [ ] 2.7.1 `spirv-val` wrapper with target environment option.
- [ ] 2.7.2 `spirv-opt` wrapper (optional, off by default; used only when asked).
- [ ] 2.7.3 `spirv-dis` wrapper for human-readable diffs in reports.
- [ ] 2.7.4 Validation diagnostics parser.
- **Acceptance:** an intentionally broken SPIR-V file produces a diagnostic with the offending instruction.

### 2.8 glslang / glslc backend
- [ ] 2.8.1 GLSL to SPIR-V compile with stage, `#version`, defines, include dirs.
- [ ] 2.8.2 Decide which binary to support first (`glslangValidator` vs `glslc`). Support the one that is easier to install in CI first.
- [ ] 2.8.3 Diagnostics parser.
- [ ] 2.8.4 Golden tests for three GLSL shaders (vertex, fragment, compute).
- **Acceptance:** GLSL input flows to SPIR-V and onward to HLSL through 2.6.

### 2.9 Optional alternative backends (not in first release)
- [ ] 2.9.1 Spike: Slang as an alternative route (HLSL/Slang source to SPIR-V/HLSL/GLSL/MSL). Compare output quality against the DXC chain on the corpus. **VERIFY** license first.
- [ ] 2.9.2 Spike: Naga and Tint for WGSL targets.
- [ ] 2.9.3 Write the findings in `docs/tools.md`. Decide whether to include.
- **Acceptance:** written decision with data, not opinion.

---

## Phase 3: Core model and deterministic pipeline

Goal: translate shaders end to end with no LLM, whenever the tool chain can do it.

### 3.1 Domain models
- [ ] 3.1.1 `ShaderLanguage` enum: `hlsl`, `glsl`, `spirv`, later `msl`, `wgsl`.
- [ ] 3.1.2 `ShaderStage` enum: vertex, fragment/pixel, compute, geometry, tessellation control/eval, mesh, task, ray stages (later).
- [ ] 3.1.3 `ShaderSource`: path, text, language, stage, entry point, defines, include dirs, content hash.
- [ ] 3.1.4 `Target`: language, version or shader model, API environment (Vulkan x.y, D3D12).
- [ ] 3.1.5 `Diagnostic`: severity, message, file, line, column, code, source tool.
- [ ] 3.1.6 `TranslationResult` and `StageResult` records, JSON serialisable.
- [ ] 3.1.7 Typed error hierarchy: `ToolMissing`, `ToolFailed`, `InvalidInput`, `UnsupportedRoute`, `LlmError`, `VerificationFailed`.
- **Acceptance:** models round-trip through JSON in unit tests.

### 3.2 Configuration
- [ ] 3.2.1 Config file `shaderflux.toml` in project root, with user-level defaults from a platform config dir.
- [ ] 3.2.2 Precedence: CLI flags, environment, project file, user file, defaults.
- [ ] 3.2.3 Settings: tool paths, default targets, include dirs, binding policy, LLM on/off, model name, max repair attempts, cache dir, report dir.
- [ ] 3.2.4 `shaderflux config show` prints the effective config with the source of each value.
- [ ] 3.2.5 API key is read only from the environment (or OS keyring later), never stored in the config file.
- **Acceptance:** precedence order covered by tests.

### 3.3 Input handling
- [ ] 3.3.1 Detect language from extension (`.hlsl`, `.fx`, `.glsl`, `.vert`, `.frag`, `.comp`, `.spv`) with an explicit `--from` override.
- [ ] 3.3.2 Detect stage from extension or `#pragma`/attribute hints, with `--stage` override.
- [ ] 3.3.3 Detect entry point (HLSL: look for `[shader("...")]` or ask; default `main`).
- [ ] 3.3.4 Handle UTF-8 with and without BOM, CRLF and LF. Reject binary input for text languages.
- [ ] 3.3.5 Size limits with a clear error.
- **Acceptance:** detection table tested with at least 20 filenames and snippets.

### 3.4 Include and macro resolution
- [ ] 3.4.1 Build an include graph for `#include "..."` and `<...>`, with search paths.
- [ ] 3.4.2 Detect cycles and missing files with precise diagnostics.
- [ ] 3.4.3 Produce a flattened single-file view for the LLM and a path-preserving view for compilers.
- [ ] 3.4.4 Track `#define` inputs from CLI and config; record the effective defines in the report.
- [ ] 3.4.5 Use the compiler's own preprocessor output where available rather than writing a custom preprocessor. Write a tiny conservative parser only for the include graph.
- **Acceptance:** a three-file shader with a cycle and a missing include yields the right diagnostics.

### 3.5 Route planner
- [ ] 3.5.1 Define the conversion graph: nodes are languages, edges are backend operations (HLSL to SPIR-V via DXC, GLSL to SPIR-V via glslang, SPIR-V to GLSL/HLSL/MSL via SPIRV-Cross).
- [ ] 3.5.2 Find the shortest valid route between source and target, or raise `UnsupportedRoute` with a helpful message.
- [ ] 3.5.3 For HLSL to HLSL (for example SM 5 to SM 6), route through SPIR-V only if the user asks, since round-tripping can change code shape.
- [ ] 3.5.4 Record each hop in the result for the report.
- **Acceptance:** route table test for all supported pairs.

### 3.6 Orchestrator
- [ ] 3.6.1 `translate(source, target, options) -> TranslationResult` for the deterministic path only.
- [ ] 3.6.2 Stop at the first failing hop and keep partial outputs.
- [ ] 3.6.3 Write outputs atomically (temp file then rename).
- [ ] 3.6.4 Never overwrite an existing output without `--force`.
- [ ] 3.6.5 Content-hash cache: skip work if input, options and tool versions are unchanged.
- [ ] 3.6.6 Structured logging with a run ID.
- **Acceptance:** golden HLSL shader translates to GLSL and the GLSL compiles back to SPIR-V that validates.

### 3.7 First vertical slice (milestone M1)
- [ ] 3.7.1 Wire `shaderflux translate in.hlsl --to glsl --stage fragment` to the orchestrator, no LLM.
- [ ] 3.7.2 Manual test on five real-world-style shaders written for the corpus.
- [ ] 3.7.3 Record what failed. This list drives Phase 5 and 6 priorities.
- **Acceptance:** M1 demo recorded as a terminal session in `docs/`.

---

## Phase 4: Analysis (reflection, bindings, conventions)

Goal: understand a shader well enough to catch porting problems before and after conversion.

### 4.1 Reflection
- [ ] 4.1.1 Extract from SPIR-V: entry points, stage, inputs/outputs with locations, descriptor sets and bindings, resource types (UBO, SSBO, textures, samplers, storage images), push constants, workgroup size.
- [ ] 4.1.2 Use SPIRV-Cross JSON reflection first. Evaluate SPIRV-Reflect as an alternative only if the JSON is insufficient.
- [ ] 4.1.3 Normalise into a `Reflection` model that is independent of the tool.
- [ ] 4.1.4 Extract uniform block member names, types, offsets and array strides.
- [ ] 4.1.5 Tests against golden SPIR-V with hand-written expected reflection.
- **Acceptance:** reflection of the five golden shaders matches expectations.

### 4.2 Binding analysis
- [ ] 4.2.1 Parse HLSL `register(...)` and `[[vk::binding]]` from source (conservative parser, report "could not parse" rather than guessing).
- [ ] 4.2.2 Build a `BindingMap` from source registers to target set/binding.
- [ ] 4.2.3 Detect collisions (two resources mapped to the same slot) and gaps.
- [ ] 4.2.4 Detect register-type mixing (`b`, `t`, `s`, `u`) that DXC maps onto one binding number space by default. **VERIFY** the default behaviour with an experiment (DXC docs say the register type is ignored, which can cause overlap).
- [ ] 4.2.5 Provide a `BindingPolicy` (shift per register type, explicit overrides) and a function that proposes one automatically.
- [ ] 4.2.6 Emit a human-readable binding table in the report.
- **Acceptance:** a shader with overlapping `b0`/`t0` is flagged, and the proposed policy removes the overlap.

### 4.3 Matrix and convention analysis
- [ ] 4.3.1 **Research spike with experiments.** Write tiny HLSL and GLSL shaders and inspect the reflected offsets and the generated code to build a verified table covering: storage order in constant buffers, `row_major`/`column_major` qualifiers, `#pragma pack_matrix`, how DXC and SPIRV-Cross treat matrix dimensions (an HLSL `float2x3` versus a GLSL `mat2x3`), and `mul` argument order. Output: `docs/matrix-conventions.md` with evidence for every row.
- [ ] 4.3.2 Define lint rules from that table, for example: `mul` used with a vector on the left versus right, matrix declared without an explicit qualifier in a shared buffer, matrix constructed from rows or columns, use of `transpose` near uploads.
- [ ] 4.3.3 Implement a token-based detector first (fast, no AST). Move to an AST only if the experiments show false positives or negatives that need it (see 4.5).
- [ ] 4.3.4 Each finding carries: rule ID, location, explanation, suggested fix, and confidence.
- [ ] 4.3.5 Test corpus: for each rule, one positive and one negative example.
- **Acceptance:** rule precision and recall measured on the corpus and recorded; no rule ships without a negative test.

### 4.4 Feature and intrinsic compatibility
- [ ] 4.4.1 Build a data file (`data/intrinsics.toml`) mapping HLSL intrinsics and GLSL built-ins to equivalents, with notes and "no equivalent" entries. Source from official docs and cite them.
- [ ] 4.4.2 Detect usage of intrinsics, semantics (`SV_*`) and extensions that the chosen target cannot express.
- [ ] 4.4.3 Detect target-version issues (for example features that need a newer `#version` or Vulkan environment).
- [ ] 4.4.4 Report each as a finding with a suggested remedy.
- **Acceptance:** at least 30 intrinsics covered with a test each.

### 4.5 AST evaluation spike
The original README promised AST analysis. Evaluate before committing.
- [ ] 4.5.1 Try tree-sitter grammars for HLSL and GLSL on the corpus. Measure parse success rate.
- [ ] 4.5.2 Try DXC's AST dump (if available in the version we pin) and Clang-style output parsing. **VERIFY** it exists in the shipped binary.
- [ ] 4.5.3 Compare against the token-based detector from 4.3.3 on the same rules.
- [ ] 4.5.4 Decide: adopt, adopt for specific rules only, or drop. Write the decision with numbers.
- **Acceptance:** a decision record in `docs/decisions/`.

### 4.6 `lint` command (milestone M2)
- [ ] 4.6.1 `shaderflux lint file --target vulkan` runs 4.2 to 4.4 and prints findings grouped by severity.
- [ ] 4.6.2 `--json` and SARIF output so results show up in code scanning tools.
- [ ] 4.6.3 Exit codes: 0 clean, 1 findings above threshold, 2 error.
- **Acceptance:** lint of the corpus is stable and documented.

---

## Phase 5: LLM layer

Goal: a safe, testable, cost-aware way to ask Claude for help.

### 5.1 Provider interface
- [ ] 5.1.1 Define `LlmProvider` protocol: `complete(request) -> LlmResponse` with token usage and stop reason.
- [ ] 5.1.2 Implement `AnthropicProvider` using the official SDK.
- [ ] 5.1.3 Implement `FakeProvider` that replays recorded responses from fixture files, used in all unit tests.
- [ ] 5.1.4 Record-and-replay tool: run once against the real API, save request/response pairs, replay in CI with no network.
- [ ] 5.1.5 Retries with backoff for transient errors, no retry for auth or invalid-request errors.
- [ ] 5.1.6 Timeouts and a per-run cost/token ceiling that aborts cleanly.
- **Acceptance:** the repair loop (Phase 6) runs fully offline in CI with the fake provider.

### 5.2 Model configuration
- [ ] 5.2.1 Model name is a config value, not hardcoded in logic. Look up current model IDs in the official docs at implementation time.
- [ ] 5.2.2 Allow separate models for cheap tasks (explanations, classification) and hard tasks (repairs).
- [ ] 5.2.3 Record model name and parameters in every report.
- **Acceptance:** changing the model requires only a config change.

### 5.3 Structured output
- [ ] 5.3.1 **VERIFY** the current official structured-output or strict tool-use mechanism and its limits in Anthropic's docs.
- [ ] 5.3.2 Define response schemas: `PatchProposal` (list of edits with file, range, replacement, reason), `Explanation`, `BindingSuggestion`.
- [ ] 5.3.3 Validate every response with Pydantic. On schema failure, retry once with the validation error, then fail cleanly.
- [ ] 5.3.4 Never execute or interpret free text from the model as commands.
- **Acceptance:** malformed fixture responses are rejected in tests.

### 5.4 Prompt design
- [ ] 5.4.1 Store prompts as versioned template files in `src/shaderflux/llm/prompts/`, not inline strings.
- [ ] 5.4.2 One prompt per task: repair compile error, fix binding layout, fix convention finding, explain a diff.
- [ ] 5.4.3 Each prompt states: the task, the source and target languages and versions, the exact diagnostics, the rules ("change as little as possible", "do not rename public symbols", "output edits only").
- [ ] 5.4.4 Include small, verified few-shot examples taken from the corpus.
- [ ] 5.4.5 Treat shader source as data: delimit it clearly and instruct the model to ignore any instructions embedded in comments or strings. Add tests with adversarial comments.
- [ ] 5.4.6 Prompt version number is recorded in reports.
- **Acceptance:** prompt changes are reviewed like code and covered by replay tests.

### 5.5 Context management
- [ ] 5.5.1 Estimate tokens before sending. Use the SDK's token counting if available.
- [ ] 5.5.2 Build the smallest sufficient context: the failing file, the included files it actually uses, the diagnostics, the relevant reflection summary.
- [ ] 5.5.3 When over budget, truncate by dropping unused includes and function bodies unrelated to the error lines, and say so in the prompt.
- [ ] 5.5.4 Use prompt caching for large stable prefixes (instructions, examples). **VERIFY** current caching semantics in the official docs.
- **Acceptance:** a 5-file shader project fits a configured budget and the log shows what was trimmed.

### 5.6 Privacy and safety controls
- [ ] 5.6.1 LLM features are off unless `--llm` or config enables them and a key exists.
- [ ] 5.6.2 `--dry-run` prints exactly what would be sent, without sending.
- [ ] 5.6.3 Optional redaction hooks (strip comments, replace string literals) before sending.
- [ ] 5.6.4 Never send environment variables, absolute paths, or files outside the shader's include graph.
- [ ] 5.6.5 Document data handling in `docs/privacy.md`.
- **Acceptance:** a test asserts that a file outside the include graph never appears in a request.

### 5.7 Cost and usage reporting
- [ ] 5.7.1 Track input/output tokens per call and total per run.
- [ ] 5.7.2 Estimate cost from a configurable price table (do not hardcode prices as facts).
- [ ] 5.7.3 Show usage at the end of each run and in the report.
- **Acceptance:** the totals in the report match the sum of recorded calls.

---

## Phase 6: Repair loop and guided transformations

Goal: use the LLM to fix what the tools cannot, with strict guardrails.

### 6.1 Patch format and application
- [ ] 6.1.1 Represent edits as line-range replacements with expected original text, so stale edits are detected.
- [ ] 6.1.2 Apply patches to a copy, never to the original file in place.
- [ ] 6.1.3 Reject patches that touch lines outside the allowed files.
- [ ] 6.1.4 Reject patches larger than a configurable fraction of the file unless `--allow-large-edits`.
- [ ] 6.1.5 Produce a unified diff for the report.
- **Acceptance:** overlapping, stale and out-of-range patches are rejected in tests.

### 6.2 Repair loop
- [ ] 6.2.1 Loop: run pipeline, collect diagnostics, ask LLM for a patch, apply, re-run. Stop on success, on attempt cap, on no progress, or on budget.
- [ ] 6.2.2 "No progress" detection: same diagnostics (after normalising line numbers) twice in a row, or an oscillation between two states.
- [ ] 6.2.3 Keep every attempt's source, diagnostics and diff for the report.
- [ ] 6.2.4 Prefer fixing the first error and re-compiling over fixing everything at once, since later errors are often caused by the first.
- [ ] 6.2.5 Never accept a patch that makes the number of errors increase, unless it is the only change available (flag it).
- **Acceptance:** with the fake provider, a scripted three-step repair converges and a scripted loop is stopped by the cap.

### 6.3 Targeted tasks
Each task is a prompt + a verifier.
- [ ] 6.3.1 **Compile error repair.** Input: source, diagnostics. Verifier: the compiler.
- [ ] 6.3.2 **Binding remap.** Input: source, binding table, collisions. Verifier: reflection shows no collisions and expected set/binding.
- [ ] 6.3.3 **Convention fix.** Input: a lint finding from 4.3. Verifier: re-run the lint rule plus the numeric test in 7.4 where possible.
- [ ] 6.3.4 **Missing intrinsic replacement.** Input: the intrinsic entry from 4.4. Verifier: compile, plus numeric test where possible.
- [ ] 6.3.5 **Explain diff.** Input: original and final source. Output: short, plain-language reasons for each change. No verifier, labelled as generated text.
- **Acceptance:** each task has at least three corpus cases with replayable fixtures.

### 6.4 `translate` with repair (milestone M3)
- [ ] 6.4.1 `shaderflux translate` runs the deterministic path first and uses the repair loop only on failure or lint findings the user opted into.
- [ ] 6.4.2 `shaderflux fix file --log compiler.log` starts from a user-supplied log, for people who already ran their own compiler.
- [ ] 6.4.3 Both commands end with a report (Phase 8).
- **Acceptance:** at least 70% of the "needs repair" corpus cases converge with the real model (target to be revisited after the first measurement, see Phase 10).

---

## Phase 7: Verification

Goal: back every claim of success with evidence.

### 7.1 Verification levels
- [ ] 7.1.1 Level 0: output exists and parses.
- [ ] 7.1.2 Level 1: output compiles with the target's compiler.
- [ ] 7.1.3 Level 2: SPIR-V validates with `spirv-val` for the target environment.
- [ ] 7.1.4 Level 3: reflection of the output matches the source's reflection (see 7.2).
- [ ] 7.1.5 Level 4: numeric or image comparison passes (7.3, 7.4).
- [ ] 7.1.6 The report states the highest level reached.
- **Acceptance:** each level has a passing and a failing test.

### 7.2 Reflection equivalence
- [ ] 7.2.1 Compare interface: inputs/outputs by location and type, resource types and counts, uniform block layout.
- [ ] 7.2.2 Allow expected differences (renamed symbols, reordered members when the policy allows it) via a configurable comparison.
- [ ] 7.2.3 Produce a readable diff of mismatches.
- **Acceptance:** a deliberately mismatched translation is caught.

### 7.3 Software-rendering comparison
- [ ] 7.3.1 Evaluate lavapipe and SwiftShader as headless Vulkan implementations. Check install effort in CI and conformance caveats. Lavapipe states it is not conformant and is for testing use.
- [ ] 7.3.2 Write a minimal headless harness (own small runner or an existing library) that renders a full-screen triangle with a fragment shader and reads back pixels. Decide between a C++ helper binary and a Python Vulkan binding.
- [ ] 7.3.3 Define a fixed set of test inputs: textures, constants, resolution.
- [ ] 7.3.4 Render both the original (compiled to SPIR-V) and the translated shader. Compare per-pixel with a tolerance and report max and mean error.
- [ ] 7.3.5 Handle nondeterminism (derivatives, uninitialised values) by documenting unsupported cases.
- [ ] 7.3.6 This is optional and marked `needs_gpu`/`needs_vulkan_sw` in tests.
- **Acceptance:** one fragment shader is rendered identically through two routes in CI.

### 7.4 Numeric checks for pure math
- [ ] 7.4.1 For functions with matrix math, generate a small compute shader that evaluates them on fixed inputs and writes to a buffer.
- [ ] 7.4.2 Run original and translated versions on the software Vulkan implementation, compare outputs with tolerance.
- [ ] 7.4.3 Use this as the verifier for 6.3.3 and 6.3.4 when possible.
- **Acceptance:** a transposed-matrix mistake is detected by this check in a test.

### 7.5 Confidence label
- [ ] 7.5.1 Combine verification level, number of repair attempts, lint findings left, and LLM involvement into `verified | partial | unverified`.
- [ ] 7.5.2 Document the rule so it is predictable.
- **Acceptance:** the label for the corpus is stable and reviewed.

---

## Phase 8: Command-line interface and reports

### 8.1 Commands
- [ ] 8.1.1 `translate`: inputs, `--from`, `--to`, `--stage`, `--entry`, `-D`, `-I`, `--out`, `--force`, `--llm/--no-llm`, `--max-attempts`, `--verify-level`, `--report`.
- [ ] 8.1.2 `fix`: shader + log.
- [ ] 8.1.3 `lint`: see 4.6.
- [ ] 8.1.4 `explain`: show the report for a previous run in plain language.
- [ ] 8.1.5 `doctor`: see 2.3.
- [ ] 8.1.6 `config show`.
- [ ] 8.1.7 `batch` and `permutations`: see Phase 9.
- **Acceptance:** `--help` for each command is complete and reviewed.

### 8.2 Output behaviour
- [ ] 8.2.1 Human output via Rich, plain output when not a TTY or with `--no-color`.
- [ ] 8.2.2 `--json` for machine consumers on every command.
- [ ] 8.2.3 Exit codes: 0 success, 1 verification or lint findings, 2 usage or environment error, 3 tool or LLM failure.
- [ ] 8.2.4 `--verbose` and `--quiet`.
- [ ] 8.2.5 Clear, actionable error messages that name the fix (for example the install hint for a missing tool).
- **Acceptance:** snapshot tests for help text and error messages.

### 8.3 Report format
- [ ] 8.3.1 JSON report (source of truth) and a Markdown renderer.
- [ ] 8.3.2 Contents: inputs and hashes, effective config, tool versions, route taken, each attempt, diffs, diagnostics, lint findings, verification results, LLM usage, confidence label, timestamps.
- [ ] 8.3.3 Report schema versioned and documented.
- [ ] 8.3.4 Optional HTML renderer later.
- **Acceptance:** a report from the corpus validates against the schema.

### 8.4 Usability
- [ ] 8.4.1 Shell completion.
- [ ] 8.4.2 `--dry-run` for every command that writes files or calls the LLM.
- [ ] 8.4.3 A `shaderflux init` that writes a commented starter `shaderflux.toml`.
- **Acceptance:** a new user can go from install to a first translation using only the CLI help.

---

## Phase 9: Batch and permutations

### 9.1 Batch
- [ ] 9.1.1 Accept a directory or glob, mirror structure in the output.
- [ ] 9.1.2 Run files in parallel with a configurable limit. Respect LLM rate limits.
- [ ] 9.1.3 Continue on failure and summarise at the end.
- [ ] 9.1.4 Resume support using the cache from 3.6.5.
- **Acceptance:** a 50-shader corpus run is repeatable and fast on a second run.

### 9.2 Permutations
- [ ] 9.2.1 Define a permutation spec (`permutations.toml`): defines with allowed values, constraints, exclusions.
- [ ] 9.2.2 Expand the spec and prune invalid combinations. Report the count before running.
- [ ] 9.2.3 Warn when the count is large (the cost grows exponentially with independent defines).
- [ ] 9.2.4 Translate each permutation deterministically first. Use the LLM only for failing ones, and try to reuse a fix across permutations that fail the same way.
- [ ] 9.2.5 Summary table: permutation, status, verification level.
- **Acceptance:** a 5-define shader with two exclusions expands to the expected number of permutations.

---

## Phase 10: Test corpus and evaluation

### 10.1 Corpus
- [ ] 10.1.1 Create `tests/corpus/` with a manifest (`manifest.toml`): ID, language, stage, origin, license, expected route, tags.
- [ ] 10.1.2 Write original shaders only, or use permissively licensed ones with clear attribution. No proprietary code.
- [ ] 10.1.3 Categories: trivial, constant buffers, textures and samplers, compute with UAVs, matrix-heavy, intrinsic-heavy, macro-heavy, multi-file, intentionally broken.
- [ ] 10.1.4 Target size: 10 shaders at M1, 40 at M3, 100 at release.
- [ ] 10.1.5 For each, record the expected outcome and the verification level it should reach.
- **Acceptance:** corpus loader and manifest validator in CI.

### 10.2 Metrics and benchmark harness
- [ ] 10.2.1 Metrics: deterministic success rate, repair success rate, mean attempts, tokens and cost per shader, wall time, verification level distribution.
- [ ] 10.2.2 `scripts/benchmark.py` runs the corpus and writes JSON + Markdown.
- [ ] 10.2.3 Store results with tool versions and model name so runs are comparable.
- [ ] 10.2.4 Baseline comparison: deterministic chain alone versus with LLM repair. This shows whether the LLM adds value.
- [ ] 10.2.5 Document how to reproduce results.
- **Acceptance:** a results table in `docs/benchmarks.md` generated by the script.

### 10.3 Regression safeguards
- [ ] 10.3.1 CI compares benchmark results to a stored baseline for the deterministic path (no API cost) and fails on regressions.
- [ ] 10.3.2 LLM benchmark runs manually or on a schedule, never on every PR.
- **Acceptance:** an intentional regression is caught in a test PR.

---

## Phase 11: Documentation

- [ ] 11.1 `docs/getting-started.md`: install tools per OS, install the package, run the first translation.
- [ ] 11.2 `docs/guides/hlsl-to-glsl.md`, `glsl-to-hlsl.md`, `hlsl-to-spirv.md`: what is automatic, what is checked, common pitfalls.
- [ ] 11.3 `docs/guides/bindings.md`: how register spaces map to descriptor sets, with diagrams.
- [ ] 11.4 `docs/matrix-conventions.md`: from 4.3.1.
- [ ] 11.5 `docs/guides/permutations.md`.
- [ ] 11.6 `docs/privacy.md`: from 5.6.
- [ ] 11.7 `docs/architecture.md` kept in sync with the code.
- [ ] 11.8 `docs/reference/cli.md` generated from the CLI definitions.
- [ ] 11.9 `docs/reference/report-schema.md`.
- [ ] 11.10 `docs/troubleshooting.md`: top errors and fixes, `doctor` output explained.
- [ ] 11.11 `examples/`: three runnable example projects with expected outputs.
- [ ] 11.12 Docs site (MkDocs or similar) published from CI once there is enough content.
- **Acceptance:** a person who has never seen the project completes the getting-started guide without help (test with one outside reader).

---

## Phase 12: Release and distribution

### 12.1 Versioning and release process
- [ ] 12.1.1 Semantic versioning, `0.x` until the CLI and report schema stabilise.
- [ ] 12.1.2 Release checklist in `docs/releasing.md`.
- [ ] 12.1.3 GitHub Actions release workflow: build sdist and wheel, run tests, publish to TestPyPI first, then PyPI using trusted publishing.
- [ ] 12.1.4 Generate release notes from the changelog.
- **Acceptance:** a release candidate installs from TestPyPI in a clean environment.

### 12.2 Docker image
- [ ] 12.2.1 Image with Python, the pinned shader tools, and the package.
- [ ] 12.2.2 Document how to mount a shader directory and pass the API key.
- [ ] 12.2.3 Scan the image for vulnerabilities in CI.
- **Acceptance:** `docker run` translates a corpus shader with no local installs.

### 12.3 Pre-release checks
- [ ] 12.3.1 Security review: subprocess handling, temp files, path traversal in includes and output paths, prompt injection handling, secrets in logs.
- [ ] 12.3.2 License review of dependencies and bundled data.
- [ ] 12.3.3 Test on Windows, macOS and Linux with real tools.
- [ ] 12.3.4 Dogfood on at least three real ports (your own or volunteers').
- [ ] 12.3.5 Update README status from "early planning" to the actual state, remove "(planned)" labels only for features that exist.
- **Acceptance:** v0.1.0 tagged (milestone M4).

---

## Phase 13: Extension points and experimental work (after v0.1)

### 13.1 Console adapter interface
- [ ] 13.1.1 Define a plugin interface (`entry_points`) for pre-conversion steps that turn a proprietary dialect into plain HLSL.
- [ ] 13.1.2 Ship only an example adapter that works on a made-up toy dialect, so the mechanism is demonstrated without proprietary content.
- [ ] 13.1.3 Document that users must have their own legal access to any SDK.

### 13.2 More targets
- [ ] 13.2.1 MSL output polish and tests.
- [ ] 13.2.2 WGSL via Naga or Tint if the spike (2.9.2) was positive.
- [ ] 13.2.3 Slang as an alternative route if the spike (2.9.1) was positive.

### 13.3 Render pipeline analysis (experimental)
This was a README feature. It is the least defined, so it starts as analysis only.
- [ ] 13.3.1 Define the input: a description of passes and draw calls (a simple JSON format, or imported from a capture tool). **DECISION** needed on which capture format to support, if any.
- [ ] 13.3.2 Detect easy wins: redundant state changes, passes that could merge, unnecessary transitions.
- [ ] 13.3.3 Output suggestions only. No automatic rewriting.
- [ ] 13.3.4 Evaluate usefulness with two real examples before building more.

### 13.4 Editor and CI integrations
- [ ] 13.4.1 GitHub Action wrapper running `lint` on shader changes in PRs.
- [ ] 13.4.2 VS Code problem-matcher or SARIF viewing guide.

---

## Phase 14: Community and maintenance

- [ ] 14.1 Triage routine for issues, labels, response targets.
- [ ] 14.2 "Porting problem" issue template feeds new corpus cases (with user permission and a license check).
- [ ] 14.3 Monthly tool-version check (see 1.4.6) and a policy for bumping pinned versions.
- [ ] 14.4 Public roadmap kept in README and issues.
- [ ] 14.5 Document how to add a new backend, lint rule, prompt, or corpus shader.

---

## Milestones

| Milestone | Contents | Exit criteria |
| --- | --- | --- |
| **M0** | Phase 1 | CI green on skeleton, licenses and templates in place |
| **M1** | Phases 2 and 3 | Deterministic HLSL to GLSL/SPIR-V works from the CLI on a 10-shader corpus |
| **M2** | Phase 4 | `lint` and `doctor` usable, matrix convention table written with evidence |
| **M3** | Phases 5, 6, 7 (levels 0 to 3) | LLM repair with offline-replay tests and verification up to reflection equivalence |
| **M4** | Phases 8, 10, 11, 12 | Reports, benchmarks, docs, v0.1.0 release |
| **M5** | Phases 7.3/7.4, 9 | Image and numeric verification, batch and permutations |
| **M6** | Phases 13, 14 | Plugins, extra targets, experimental pipeline analysis |

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| External tools change behaviour or lose maintenance | Medium | High | Pinned versions, weekly drift CI, pluggable backends, maintenance check in 2.1.3 |
| LLM produces plausible but wrong shaders | High | High | Verification levels, reflection and numeric checks, confidence labels, diffs for human review |
| Matrix and convention bugs slip through | High | High | Experiment-based convention table, dedicated lint rules, numeric tests |
| Software rasterizer results differ from real GPUs | Medium | Medium | Label as regression aid, document limits, optional only |
| Users send confidential code to a third party | Medium | High | Off by default, dry-run, redaction, clear privacy docs |
| Prompt injection through shader comments | Medium | Medium | Delimited data, schema-validated output, patch guardrails, adversarial tests |
| API cost surprises | Medium | Medium | Token estimates, budget ceilings, deterministic-first approach |
| Scope creep into engines or pipelines | High | Medium | Experimental phase, decision records, milestone gates |
| Installation of external tools is hard for users | High | Medium | `doctor` with install hints, Docker image |
| Legal exposure from proprietary shader content | Low | High | Corpus rules, no console code, license manifest |
| Single-maintainer bandwidth | High | Medium | Small milestones, good docs, contribution templates |

---

## Definition of done (applies to every task)
1. Code merged with tests (unit, and integration where tools are involved).
2. Lint and type checks pass in CI.
3. Docs updated (user-facing change means a docs change).
4. Changelog entry added.
5. Any **VERIFY** items in the task were resolved and the evidence recorded.
6. No proprietary content, secrets or absolute local paths committed.

---

## Open questions for review
1. Approve or change decisions D1 to D9.
2. Is v0.1 allowed to ship without image comparison (7.3)? My recommendation: yes.
3. Should Slang be evaluated early (2.9.1), since it could replace parts of the chain?
4. How many real shaders can you contribute for dogfooding in 12.3.4, and under what license?
5. Do you want the render pipeline analysis feature kept in the README, or removed until it is better defined?
