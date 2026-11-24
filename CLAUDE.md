# ShaderFlux-AI: notes for Claude

Open-source CLI that helps people port shaders to PC. A deterministic tool chain
(DXC, SPIRV-Cross, SPIRV-Tools, glslang) does the mechanical work, lint rules find
known porting traps, `shaderflux fix` applies the mechanical fixes (no AI), and an optional, experimental LLM (`translate --repair`, off by default, user's own key) helps with the rest. **The project must stay fully useful with no API key**: never make a feature depend on the LLM, and never use a maintainer key. Real tools verify
results. Plan: `docs/PLAN.md`. Evidence for the rules: `docs/pain-points.md` and
`docs/matrix-conventions.md`.

## Commands

```bash
make setup     # venv + dev deps + pre-commit (uses uv)
make check     # ruff + mypy --strict + unit tests (what CI runs)
make test-all  # also runs tests that need real tools
pytest -m needs_tools   # integration tests; skip themselves if a tool is missing
```

Tool binaries live on `PATH` (apt: spirv-tools, glslang-tools, spirv-cross, glslc).
`dxc` is usually missing; see "Known gaps".

## Layout

`src/shaderflux/` is a one-way stack, enforced by `tests/unit/test_architecture.py`
(details and diagram: `docs/architecture.md`):

`core` < `source`, `tools` < `verify`, `analysis` < `pipeline` < `llm` < `reporting` < `workflows` < `cli`

- `tools` is the only code that spawns processes (`tools/runner.py`); `llm/anthropic_provider.py`
  is the only code that talks to the API; only `cli` prints or imports Typer/Rich.
- Logic goes in `workflows/` (data in, data out), not in `cli/`. `api.py` is the public Python API.
- Adding a package, or an import that breaks the layering, fails the architecture test: update its
  `ALLOWED` table and `docs/architecture.md` on purpose, not to make the test pass.

## Rules for working on this repo

1. **Never claim something is verified unless a real tool checked it.** Plan checkboxes
   mean "done and tested"; partial or unverified work gets an italic note, not a tick.
2. **Mark facts you could not confirm as VERIFY** (in code and docs), and put them in
   `docs/PLAN.md`. Do not state tool behaviour from memory; run the tool.
3. External tools are called only through `tools/runner.py`: argument lists, no shell,
   timeouts, output caps. Validate anything user-supplied that reaches a command line
   (see `check_define_name`, `check_spirv_env`).
4. **No proprietary or NDA-covered shader code** (console SDKs) in code, tests, prompts
   or docs. Corpus shaders must be original or permissively licensed.
5. For Claude API code, load the `claude-api` skill first and follow current model IDs and parameter rules. API keys are read only from `ANTHROPIC_API_KEY`; config files containing one are
   rejected. Never log or store a key.
6. Lint rules must carry a confidence level and a concrete fix, and each needs a
   positive and a negative test. New false positives become new corpus cases in
   `tests/corpus/lint/` (see `lint_manifest.toml`).
7. Keep CLI exit codes: 0 ok, 1 translation/lint failure, 2 bad input or missing tool,
   3 tool failure.

## Gotchas found the hard way

- `spirv-val` wants `--target-env <env>` (separate argument); `spirv-opt` wants
  `--target-env=<env>`. SPIRV-Tools spells `spv1.5` where glslang/DXC say `spirv1.5`.
- Ubuntu's `spirv-cross` is a 2021 build with no `--version`; its version is "unknown".
- Pass shader files to tools by relative name with `cwd` set, or diagnostics leak
  temporary absolute paths.
- Rich treats `[[vk::binding]]` as markup: always `rich.markup.escape` user-facing text.
- `GLSL -> GLSL` needs `--roundtrip` on purpose; it rewrites the code.
- Use absolute paths in shell commands; a stray `cd` into a subfolder changes the working directory.

## Lessons from reviewing my own work

- Code that scans untrusted shader text must be **linear time**. Avoid adjacent `\s*` quantifiers, unbounded `[^x]*` before a required token, scanning backwards with a regex, and per-match `text.count("\n", 0, pos)` (use `core.text.LineIndex`). `tests/unit/test_lint_performance.py` feeds hostile inputs to every rule; extend it when adding a rule.
- **A regression test must be shown to fail on the old code** (restore the old file from git, run it, restore the fix). One test here passed on the bug because a new safety limit short-circuited it.
- Run a clean wheel install (`uv build --wheel`, install in a fresh venv) before claiming packaging works; editable installs hide missing package data.
- Anything that costs money or time (an LLM call) must validate its output paths and option combinations **first**.
- CI found what local runs could not. Shell scripts must work on **bash 3.2** (macOS default: no `globstar`, `mapfile`, `${x,,}`, `declare -A`); Windows shells expand no globs, so the CLI expands patterns itself (`expand_patterns`). CI runs tests **with coverage**, which can slow tight Python loops 25x, so timing tests assert how cost *scales* (`_assert_scales`), never an absolute time. Rich colours CLI `--help` on CI, so tests that read help text strip ANSI codes first.
- Structure is checked by tests, not by memory: layering, one-place imports of `subprocess` and `anthropic`, UI libraries only in `cli`, no `print` in library code, and rule ids matching their documentation (`tests/unit/test_architecture.py`).
- Child processes get a scrubbed environment (`tools/runner.py:clean_environment`); never pass secrets to tools.

## Known gaps (keep these honest in README and PLAN)

- The DXC backend (`tools/dxc.py`) is exercised against a real **DXC 1.9 (Linux)** only in CI (job `dxc-tests`, downloaded from Microsoft's release); locally `dxc` is usually missing and those tests skip. Verified there: flag syntax, the default binding collision and the proposed fix, HLSL to GLSL, version parsing, matrix packing defaults, `#pragma pack_matrix`, and that SM5 HLSL from SPIRV-Cross compiles. **Not** verified: Windows DXC, other DXC versions, `-fvk-use-gl-layout`. `scripts/dxc_experiments.py` prints facts about DXC for the docs.
- Lint rules are heuristic (token based). Their 100% score on `tests/corpus/lint/` is a
  regression guard written by the same author, not independent evidence.
- CI was green on pull request #1 at the last check (lint, unit tests on Ubuntu, macOS and Windows with Python 3.11 to 3.13). Always look at the latest run rather than trusting this line; it took three pushes to get green the first time, because CI found things local runs could not (see "Lessons"). Windows skips about 77 POSIX-only tests, so Windows coverage is thinner. An `integration-tests` job (Ubuntu only) installs the apt tools and runs the `needs_tools` tests without `dxc` (the DXC tests skip there); the `dxc-tests` job runs them with DXC. An `action-smoke` job runs `action.yml` itself on this repository's shaders (clean passes, collision fails, globs and SARIF checked); the `upload-sarif` step is skipped there and has never run.
- The LLM layer (`llm/`, `translate --repair`) is tested only with a scripted fake model. It has **never run against the live API** (no key was available), so real prompt quality and success rates are unknown. The Anthropic request uses `output_config` (effort and JSON schema), no `thinking`/sampling parameters (current models reject them), and tries server-side refusal fallbacks first, retrying without them if rejected.
- `fix` (`analysis/autofix.py`, `workflows/fix_file.py`) handles BND001 and MAT002 in HLSL only, by insertion; BND001 is withheld when the shader includes other files. Unit-tested; its real-DXC test (`test_the_fix_command_output_compiles_to_distinct_slots_without_any_flags`) runs only in the `dxc-tests` CI job, and so does `test_fix_verify_confirms_the_fix_and_catches_a_partial_one` (`fix --verify`); check that run before calling it verified.
- Verification beyond SPIR-V validation, reports, batch mode and image comparison are not built.
