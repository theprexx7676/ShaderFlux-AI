# ShaderFlux-AI

**An open-source assistant for getting shaders running on PC.**

ShaderFlux-AI helps developers who are porting a game or graphics project to PC and are stuck on the shader step. It wraps the standard open-source shader compilers and uses an LLM (Claude) for the parts those tools cannot do: fixing convention mismatches, mapping bindings, replacing missing intrinsics and explaining compiler errors.

> **Status: early development (v0.0.1, not released).** Working today: `shaderflux lint` and `explain` for HLSL and GLSL (binding collisions, matrix-convention traps, intrinsic differences), translation of GLSL input to HLSL, GLSL or SPIR-V with SPIR-V validation and a re-check of the generated code, run reports (`--report`), `doctor`, `config show` and a GitHub Action. **Not yet proven:** HLSL *translation* has never run against a real DXC, `translate --repair` (Claude proposes small fixes, the real compiler checks them) has never run against the live API, and the Action's upload-to-code-scanning step has never been exercised. **Not built:** reflection and image comparison, batch mode, a `fix` command. See the [roadmap](#roadmap) and the [detailed plan](docs/PLAN.md).

## Who is this for?

- Developers moving a project from another platform to PC (Vulkan or DirectX 12).
- Engine and tools programmers who maintain HLSL or GLSL shaders for several backends.
- Hobbyists and students learning why a shader that works in one API breaks in another.

## Why it exists

Translating shaders between platforms is slow and error-prone. The mechanical part is largely solved by tools such as DXC and SPIRV-Cross. The remaining work is where people lose days:

- Register and binding layouts that don't map one-to-one.
- Matrix conventions, such as storage order and `mul` argument order.
- Intrinsics, semantics and features that exist on one side only.
- Cryptic compiler errors after an automatic conversion.

ShaderFlux-AI automates the mechanical steps, uses the LLM only for the judgment calls, and **checks results with real compilers and validators wherever they are installed**. Each report says exactly which checks ran and which did not.

## Demo

A GLSL fragment shader goes in:

```glsl
#version 450
layout(location=0) in vec2 uv;
layout(location=0) out vec4 color;
layout(set=0,binding=1) uniform sampler2D tex;
layout(set=0,binding=0) uniform Params { mat4 mvp; vec4 tint; } p;
void main(){ color = texture(tex, uv) * p.tint; }
```

```bash
shaderflux translate textured.frag --to hlsl --hlsl-model 50
```

HLSL comes out. This is real output from the current version, with the register bindings and the matrix qualifier already handled:

```hlsl
cbuffer Params : register(b0)
{
    row_major float4x4 p_mvp : packoffset(c0);
    float4 p_tint : packoffset(c4);
};

Texture2D<float4> tex : register(t1);
SamplerState _tex_sampler : register(s1);
...
void frag_main()
{
    color = tex.Sample(_tex_sampler, uv) * p_tint;
}
```

Note `row_major`: the GLSL matrix was column-major, and the translation flips the qualifier so the memory layout stays identical. This is exactly the kind of detail that silently breaks ports when done by hand.

Errors are reported with file and line, and a non-zero exit code:

```text
$ shaderflux translate broken.frag --to hlsl
broken.frag:3: error: 'undefined_thing' : undeclared identifier
translation failed
```

## Find porting bugs before they bite

```text
$ shaderflux lint collision.hlsl
collision.hlsl:2  error  BND001  Params (b0), albedo (t0), samp (s0), output (u0) all map to Vulkan
set 0, binding 0: DXC ignores the register type by default
    fix: compile with -fvk-s-shift 3 all -fvk-t-shift 1 all -fvk-u-shift 4 all (or use
[[vk::binding]] attributes)
collision.hlsl:4  note  MAT002  matrix 'mvp' in a constant buffer has no explicit
row_major/column_major, so its memory layout depends on the compiler's default packing and flags
    fix: write 'row_major' or 'column_major' on 'mvp' (or add #pragma pack_matrix) so the layout
matches what the CPU uploads

1 error, 1 note in 1 file(s).
Run shaderflux explain <RULE> for the why and how to fix.
```

`shaderflux explain BND001` gives the short story: why it happens, how to fix it, and how sure the tool is. The problems it looks for (bindings that collide, matrices that end up transposed, `mul` written in two orders, functions that are not plain renames) are the ones developers keep hitting; the sources are in [docs/pain-points.md](docs/pain-points.md) and the experiments in [docs/matrix-conventions.md](docs/matrix-conventions.md). Use `--sarif` to see findings in GitHub code scanning, or `--json` for scripts.

## What you get

**The end result:** one command-line tool, `shaderflux`, that takes a shader and gives you back a translated version plus a report that says exactly what was checked.

1. **A translated shader.** HLSL, GLSL or SPIR-V in; HLSL, GLSL, SPIR-V or MSL out, produced by the standard compiler tools rather than guessed.
2. **A verdict and a report.** Each result says how far it was checked, from what really ran: the source compiled, the SPIR-V validated, the generated GLSL/HLSL compiled again. The report also lists what was **not** checked. Planned additions are same resources as the original and same pixels. Nothing is called "checked" unless the tool ran.
3. **A list of porting risks.** Before you ship, it flags the classic traps: resource bindings that collide, matrices that may be transposed, `mul` written two different ways, intrinsics that behave differently between APIs.
4. **Plain-language fixes.** When the tools fail or something looks wrong, the LLM proposes a small, reviewable change and explains why, instead of leaving you with a wall of compiler errors.

**How it helps people:**
- *Small teams and solo developers* get the same tool-chain knowledge that big studios keep in-house, without having to learn every compiler flag.
- *People learning graphics programming* see exactly what changed between APIs and why.
- *Anyone porting a project* spends less time on the repetitive 80% (conversion, bindings, validation) and more on the 20% that needs human judgment.
- *Everyone* can trust the output more, because it is checked by real compilers and every change is a diff you can read.

## How it compares

Good shader translators already exist, and ShaderFlux-AI builds on them rather than replacing them:

| Project | What it is |
| --- | --- |
| [ShaderConductor](https://github.com/Microsoft/ShaderConductor) | Glues DXC and SPIRV-Cross to cross-compile HLSL |
| [SDL_shadercross](https://docsearch.algolia.com/mcp/docs/repo/libsdl-org/sdl_shadercross) | Library and CLI for converting between shader formats |
| [Naga](https://kvark.github.io/naga/shader/2022/02/17/shader-translation-benchmark.html) / Tint | Rust and Google translators used in WebGPU stacks |
| [CrossTL](https://github.com/CrossGL/crosstl) | Translator built on its own intermediate language |

ShaderFlux-AI uses the same standard compilers underneath. The goal is to add what a translator alone does not give you: **checks for porting traps** (bindings, matrix conventions, intrinsics), **explanations and small fixes** when conversion fails, and **a clear statement of what was and was not verified**. The porting-trap checks and run reports work today; AI-assisted fixes are built but not yet proven against the live API; same-pixel comparison is planned.

## How it works

```
 source shader (HLSL / GLSL / SPIR-V)
        │
        ▼
 1. Analyse   ── resolve #includes, detect stage and language;
        │         `lint` flags known porting risks (bindings, matrix order, ...)
        ▼
 2. Convert   ── deterministic toolchain (DXC / glslang → SPIR-V → SPIRV-Cross)
        │
        ▼
 3. Repair    ── only with --repair, only if compilation fails: the LLM proposes
        │         small line edits; the real compiler decides whether they worked
        ▼
 4. Check     ── validate the SPIR-V (spirv-val) and compile the generated GLSL/HLSL
        │         again; planned: compare resources and rendered pixels
        ▼
 translated shader + report (what changed, what was and was not checked)
```

The LLM never has the last word: a fix is kept only if the real compiler accepts it, and anything that was not checked is labelled as such in the report.

## Features

| Feature | Status |
| --- | --- |
| Translation between HLSL, GLSL, SPIR-V and MSL | GLSL input works and is tested with real tools. HLSL input is implemented but **unverified** (needs DXC). MSL output is implemented but untested |
| Binding collision check and fix flags | Works (the printed DXC flags still need confirming against a real DXC) |
| Matrix-convention and intrinsic checks | Work; heuristic, each finding has a confidence level |
| `explain` for every rule | Works |
| Output re-check and run reports | Work for GLSL output; HLSL output is re-checked only if DXC is installed |
| AI-assisted compile-error repair | Built, tested with a scripted model, **never run against the live API** |
| Reflection and image comparison | Planned |
| Batch and permutations | Planned |
| Works fully offline | Yes, everything except `--repair` |

## Usage

Working today (deterministic tool chain, no LLM):

```bash
# Check which external tools are installed
shaderflux doctor

# Translate a shader (prints to stdout, or use --out)
shaderflux translate lighting.frag --to hlsl --hlsl-model 50
shaderflux translate pass.vert --to spirv --out pass.spv

# Defines, include directories, machine-readable result
shaderflux translate lighting.frag --to hlsl -D TINT=0.5 -I shaders/common --json

# Check shaders for known porting traps (does not change them)
shaderflux lint lighting.hlsl
shaderflux lint 'shaders/**/*.hlsl'          # glob patterns work on every platform
shaderflux lint lighting.hlsl --target any --ignore MAT003 --fail-on warning

# Understand a finding
shaderflux explain BND001

# Write a report of what was done and what was and was not checked
shaderflux translate lighting.frag --to hlsl --report report.md

# Show the effective configuration and where each value comes from
shaderflux config show
```

Exit codes: `0` success, `1` the translation failed (for example a compile error), `2` bad input or a missing tool, `3` a tool failed while running.

AI-assisted repair (needs `ANTHROPIC_API_KEY`; sends your shader, see [docs/privacy.md](docs/privacy.md)):

```bash
# See exactly what would be sent, and send nothing
shaderflux translate broken.frag --to hlsl --repair --dry-run

# Try to fix a compile error with Claude, review the diff, save the corrected source
shaderflux translate broken.frag --to hlsl --repair --write-fixed broken.fixed.frag
```

The model only proposes line edits. The tool rejects stale or oversized edits, never touches your file, and keeps a fix only if the real compiler accepts it.

Planned, not built yet: `shaderflux fix` from a compiler log.

## Use it in GitHub Actions

Run the lint on every pull request that touches shaders, and see the findings in GitHub's code-scanning tab:

```yaml
- uses: actions/checkout@v4
- uses: theprexx7676/ShaderFlux-AI@main   # pin a release tag or commit once there is one
  with:
    paths: "shaders/**/*.hlsl shaders/**/*.glsl"
    fail-on: error          # error | warning | note | never
    upload-sarif: "true"    # needs `security-events: write`
```

A complete workflow is in [examples/workflows/lint-shaders.yml](examples/workflows/lint-shaders.yml). The script behind the Action (`scripts/action-lint.sh`) is covered by tests, including inputs that try to inject shell commands. CI runs the Action on this repository's own shaders on every pull request: a clean shader passes, a binding collision fails the job, globs expand, and the SARIF is checked. The **upload to code scanning has not been exercised** (it needs repository permissions), and the pinned `upload-sarif@v3` should be checked against the current major version.

## Use it as a Python library

Everything the command line does is available without it, through a small public API (it never prints and never imports the CLI):

```python
from pathlib import Path
from shaderflux.api import ShaderLanguage, TranslateRequest, lint_file, run_translate

for finding in lint_file("shaders/lighting.hlsl").findings:
    print(finding.format())

outcome = run_translate(
    TranslateRequest(input_file=Path("pass.frag"), target_language=ShaderLanguage.HLSL)
)
```

How the code is organised, and how to add a lint rule or a tool backend, is in [docs/architecture.md](docs/architecture.md).

## Requirements

- Python 3.11 or newer.
- External tools on your `PATH` (`shaderflux doctor` shows what is missing and how to install it):
  - [SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross) and the [SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools) suite (`spirv-val`). Prefer a recent SPIRV-Cross: some distribution packages are years old.
  - [glslang](https://github.com/KhronosGroup/glslang) or `glslc` for GLSL input.
  - [DXC](https://github.com/microsoft/DirectXShaderCompiler) for HLSL input and for re-checking generated HLSL. It ships with the Vulkan SDK.
  - `lint` and `explain` need none of these.
- An Anthropic API key (`ANTHROPIC_API_KEY`) only for `translate --repair`. Nothing else needs it.

## Privacy

Only `translate --repair` talks to the network: when a shader fails to compile it sends that shader, the files it includes and the compiler errors to the Anthropic API. Use `--dry-run` to see exactly what, and read [docs/privacy.md](docs/privacy.md). Everything else (lint, explain, translate without `--repair`) runs entirely on your machine.

## Scope and limitations

- **No proprietary console code.** Shaders written for console SDKs are usually covered by NDAs, so this repository does not include or support console-specific dialects. If you have legitimate access, convert them to plain HLSL first. An adapter interface for that is on the roadmap.
- **"Correct" means verified within limits.** Passing compilation and validation does not prove identical rendering. Planned image comparison would use a software rasterizer, which is a testing aid and not a substitute for testing on real GPUs.
- **LLM output can be wrong.** Review the diff and the report before shipping a translated shader.
- **Tool versions matter.** Results depend on the versions of the external compilers. The tool records them in each report.

## Roadmap

- [x] Project idea and scope
- [x] Foundation: repository layout, tooling, packaging (CI green on Linux, macOS and Windows with Python 3.11 to 3.13)
- [ ] Deterministic conversion pipeline with compiler wrappers (done for GLSL input; HLSL needs DXC verification)
- [x] Analysis: reflection, binding collisions, matrix and intrinsic checks, `lint` and `explain` (DXC-side verification pending)
- [x] LLM repair loop with compiler verification (offline-tested; live API not yet exercised)
- [x] Output re-check, verdicts and run reports
- [x] GitHub Action for `lint` (runs in CI on this repository; SARIF upload not yet exercised)
- [ ] Command-line tool and first release (no release yet)
- [ ] Test corpus and benchmarks
- [ ] Batch and permutation support
- [ ] Documentation and tutorials
- [ ] Experimental: render pipeline analysis

The full breakdown, with acceptance criteria, is in [docs/PLAN.md](docs/PLAN.md).

## Help wanted

The most useful things you can do right now:

- **Try it on a real shader and tell us what breaks.** Use the "Porting problem" issue template. A minimal failing shader is gold.
- **Verify the HLSL path.** HLSL input needs a real DXC to confirm; if you have the Vulkan SDK installed, run `pytest -m needs_tools` and report the result.
- **Contribute small test shaders** (your own code only; no console SDK or NDA material). See `CONTRIBUTING.md`.
- **Review the [plan](docs/PLAN.md).** Disagreements and missing pitfalls are welcome.

If the project is useful to you, a star helps other graphics developers find it.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and rules. Useful early help includes small test shaders with known tricky behaviour, reports of porting problems you have hit, and review of the plan.

## Acknowledgments

ShaderFlux-AI builds on the work of the DXC, SPIRV-Cross, SPIRV-Tools, glslang and Slang projects, among others.

## License

Distributed under the [MIT License](LICENSE). Third-party tools that ShaderFlux-AI runs keep their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
