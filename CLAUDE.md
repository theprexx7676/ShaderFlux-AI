# ShaderFlux-AI: notes for Claude

Open-source CLI that helps people port shaders to PC. A deterministic tool chain
(DXC, SPIRV-Cross, SPIRV-Tools, glslang) does the mechanical work, lint rules find
known porting traps, and an optional LLM (`translate --repair`, off by default) helps with the rest. Real tools verify
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

`src/shaderflux/`: `cli` (Typer commands), `core` (models, config, errors),
`tools` (the only code that spawns processes, via `tools/runner.py`), `pipeline`
(includes, routes, cache, translate), `analysis` (reflection, bindings, lint
rules), `llm` (provider, prompts, patches, repair loop), `verify` / `reporting` (still empty).
Dependency direction: `cli -> pipeline -> analysis/tools -> core`.

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
- Child processes get a scrubbed environment (`tools/runner.py:clean_environment`); never pass secrets to tools.

## Known gaps (keep these honest in README and PLAN)

- The DXC backend (`tools/dxc.py`) and HLSL translation are **unverified against a real
  `dxc`**; flag spellings are marked VERIFY. Tests in `tests/integration/test_dxc.py`
  skip until `dxc` exists.
- Lint rules are heuristic (token based). Their 100% score on `tests/corpus/lint/` is a
  regression guard written by the same author, not independent evidence.
- CI is green on pull request #1 (head `d390e72`): lint plus unit tests on Ubuntu, macOS and Windows with Python 3.11 to 3.13. It took three pushes to get there, because CI found things local runs could not (see "Lessons"). Windows skips about 77 POSIX-only tests, so Windows coverage is thinner. An `integration-tests` job (Ubuntu only) installs the apt tools and runs the `needs_tools` tests; there is no `dxc` in CI, so the DXC tests skip. CI does not run the GitHub Action itself.
- The LLM layer (`llm/`, `translate --repair`) is tested only with a scripted fake model. It has **never run against the live API** (no key was available), so real prompt quality and success rates are unknown. The Anthropic request uses `output_config` (effort and JSON schema), no `thinking`/sampling parameters (current models reject them), and tries server-side refusal fallbacks first, retrying without them if rejected.
- Verification beyond SPIR-V validation, reports, batch mode and the `fix` command are not built.
