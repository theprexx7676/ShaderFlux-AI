# Architecture

ShaderFlux-AI is a pipeline in which deterministic tools do the mechanical work,
an LLM handles judgment calls, and real compilers and validators verify results.

```
 source shader (HLSL / GLSL / SPIR-V)
        |
        v
 1. Analyse   parse, resolve #includes, detect stage and language, lint for known risks
        |
        v
 2. Convert   deterministic toolchain (DXC -> SPIR-V -> SPIRV-Cross)
        |
        v
 3. Repair    LLM proposes small diffs, driven by compiler diagnostics
        |
        v
 4. Verify    compile, spirv-val, reflection comparison, optional image/numeric check
        |
        v
 translated shader + report
```

## Packages (`src/shaderflux/`)

| Package | Responsibility |
| --- | --- |
| `cli` | Command definitions, output formatting, exit codes. No business logic. |
| `core` | Domain models (sources, targets, diagnostics, results), configuration, errors, logging. |
| `tools` | One backend per external program. The only place that spawns subprocesses. |
| `pipeline` | Include resolution, route planning, orchestration, caching. |
| `analysis` | Reflection, binding analysis, matrix-convention and intrinsic lint rules. |
| `llm` | Provider interface, prompts, context building, patch proposals, repair loop. |
| `verify` | Verification levels, reflection equivalence, software-render and numeric checks. |
| `reporting` | Report models and renderers (JSON, Markdown). |

## Dependency direction

`cli` -> `pipeline` -> (`analysis`, `llm`, `verify`, `tools`) -> `core`.
`core` imports nothing else from the project. `tools` never imports `llm`.

## Principles

1. Tools first, LLM second.
2. Nothing is "done" until verified; results carry a verification level.
3. The LLM proposes small diffs, never unreviewed whole-file rewrites.
4. The deterministic pipeline works offline.
5. No shader leaves the machine unless the user enabled LLM features.

The full task list is in [PLAN.md](PLAN.md).
