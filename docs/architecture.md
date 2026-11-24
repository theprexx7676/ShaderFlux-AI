# Architecture

ShaderFlux-AI is a pipeline in which deterministic tools do the mechanical work, lint rules find
known porting traps, an optional LLM helps with compile errors, and real compilers check the
result.

```
 source shader (HLSL / GLSL / SPIR-V)
        |
        v
 1. Analyse   resolve #includes, detect stage and language; `lint` flags known porting risks
        |
        v
 2. Convert   deterministic tool chain (DXC / glslang -> SPIR-V -> SPIRV-Cross)
        |
        v
 3. Fix       `fix`: deterministic insertions (BND001, MAT002), no AI. Optional and experimental:
        |     --repair, where an LLM proposes small line edits and the real compiler decides
        v
 4. Check     validate the SPIR-V, compile the generated GLSL/HLSL again
        |
        v
 translated shader + report (what changed, what was and was not checked)
```

## Layers

The code is a one-way stack. A package may import only the packages listed for it, and
`tests/unit/test_architecture.py` fails if that stops being true.

```
 cli  ──────────────────────────────  commands: options in, text out (Typer, Rich)
  │
 workflows  ────────────────────────  what a command does, as data in and data out
  │
 reporting  ────────────────────────  run reports (JSON, Markdown)
  │
 llm  ──────────────────────────────  provider, prompts, safe patches, repair loop
  │
 pipeline  ─────────────────────────  routes, cache, translate, output writing
  │
 analysis        verify  ───────────  lint rules, bindings, reflection  |  verdicts, re-check
  │               │
 source          tools  ────────────  file and include handling  |  external tool backends
  │               │
 core  ─────────────────────────────  models, config, errors, logging, text helpers
```

| Package | Responsibility | May import |
| --- | --- | --- |
| `core` | Domain models, configuration, typed errors, logging, `LineIndex` | nothing |
| `source` | Language and stage detection, `#include` graph, glob expansion | `core` |
| `tools` | One backend per external program; **the only code that spawns processes** (`tools/runner.py`) | `core` |
| `verify` | Verdicts (`levels`) and re-compiling generated code (`recompile`) | `core`, `tools` |
| `analysis` | Reflection, binding analysis, matrix and intrinsic rules, the lint engine, rule documentation | `core`, `source`, `tools` |
| `pipeline` | Route planning, cache, `translate`, atomic output | `core`, `source`, `tools`, `verify` |
| `llm` | Provider interface, Anthropic provider, prompts, patches, repair loop; **the only code that talks to the API** (`anthropic_provider.py`) | `core`, `source`, `tools`, `pipeline` |
| `reporting` | Report model and renderers | `core`, `analysis`, `llm`, `verify` |
| `workflows` | `translate_file`: option checks, translate or repair, writing outputs and reports; `fix_file`: deterministic fixes (`analysis/autofix.py`), no AI; `init_project`: starter files | everything below |
| `cli` | Typer commands; **the only code that prints or uses Typer and Rich** | everything below |
| `api.py` | The public Python API (re-exports) | the library layers, never `cli` |

Also enforced by tests: library code never calls `print`, `subprocess` is imported in one place,
`anthropic` in one place, and the package has no import cycles.

## Using it as a library

```python
from pathlib import Path
from shaderflux.api import ShaderLanguage, TranslateRequest, lint_file, run_translate

for finding in lint_file("shaders/lighting.hlsl").findings:
    print(finding.format())

outcome = run_translate(
    TranslateRequest(input_file=Path("pass.frag"), target_language=ShaderLanguage.HLSL)
)
```

## Principles

1. Tools first. The project must be fully useful with no API key, account or network; the LLM is an optional, experimental extra that uses the user's own key.
2. Nothing is "checked" unless a real tool ran; reports say what was not checked.
3. The LLM proposes small diffs, never unreviewed rewrites, and the compiler has the last word.
4. Everything except the optional `--repair` works offline.
5. No shader leaves the machine unless the user asked for `--repair`.

## Adding things

**A lint rule.** Put the check in the right module of `analysis/` (or a row in
`analysis/data/intrinsics.toml`), give it a rule id, add its entry to `analysis/rules.py` (title,
why, fix, evidence), a positive and a negative test, a case in `tests/corpus/lint/`, and a hostile
input in `tests/unit/test_lint_performance.py`. The architecture test fails if the id is emitted
but not documented, or documented but never emitted.

**A tool backend.** Add a module in `tools/` that implements one of the protocols in
`tools/base.py`, validates user-supplied values with `tools/validation.py`, runs the program only
through `tools/runner.py`, and register it in `tools/registry.py`. Test its output parser with
text captured from the real tool.

**A command.** Put the logic in `workflows/` as a function from a request dataclass to an outcome
dataclass, test it without the command line, and add a thin `cli/<name>_cmd.py` that maps options to
the request and the outcome to output.
