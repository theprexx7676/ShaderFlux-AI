# ShaderFlux-AI

**An open-source assistant for getting shaders running on PC.**

ShaderFlux-AI helps developers who are porting a game or graphics project to PC and are stuck on the shader step. It wraps the standard open-source shader compilers and uses an LLM (Claude) for the parts those tools cannot do: fixing convention mismatches, mapping bindings, replacing missing intrinsics and explaining compiler errors.

> **Status: early development.** Working today: `shaderflux lint` and `explain` for HLSL and GLSL (binding collisions, matrix-convention traps, intrinsic differences), translation of GLSL input to HLSL, GLSL or SPIR-V with validation, `doctor` and `config show`. HLSL *translation* is implemented but **not yet verified against a real DXC**. `translate --repair` (Claude proposes small fixes to compile errors, the real compiler checks them) is built and tested offline but **has not yet run against the live API**. Verification beyond SPIR-V validation, reports and batch mode are **planned, not built**. See the [roadmap](#roadmap) and the [detailed plan](docs/PLAN.md).

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

ShaderFlux-AI automates the mechanical steps, uses the LLM for the judgment calls, and **checks every result with real compilers and validators** before calling it done.

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

**The end result:** one command-line tool, `shaderflux`, that takes a shader and gives you back a PC-ready version plus a report you can trust.

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

ShaderFlux-AI uses the same standard compilers underneath. The goal is to add what a translator alone does not give you: **checks for porting traps** (bindings, matrix conventions, intrinsics), **explanations and small fixes** when conversion fails, and **a clear statement of what was and was not verified**. Several of these are still planned; see the roadmap.

## How it works

```
 source shader (HLSL / GLSL / SPIR-V)
        │
        ▼
 1. Analyse   ── parse, resolve #includes, detect stage and language,
        │         flag known porting risks (matrix order, bindings, ...)
        ▼
 2. Convert   ── deterministic toolchain first (DXC → SPIR-V → SPIRV-Cross)
        │
        ▼
 3. Repair    ── if conversion fails or output looks wrong, the LLM proposes
        │         a fix as a small diff, using compiler errors as feedback
        ▼
 4. Verify    ── compile, validate (spirv-val), compare reflection data,
        │         optionally render and compare images
        ▼
 translated shader + report (what changed, why, confidence)
```

The LLM never has the last word. A translation is only reported as successful if it passes the checks in step 4, and anything that was not verified is labelled as such.

## Features (planned)

| Feature | What it does |
| --- | --- |
| Shader translation | HLSL, GLSL and SPIR-V in; HLSL, GLSL, SPIR-V (and MSL through SPIRV-Cross) out |
| Binding mapping | Finds register/space collisions and proposes the DXC flags that fix them (**working**) |
| Convention checks | Detects likely matrix-layout and `mul`-order mismatches (**working**, heuristic) |
| Error repair | Reads compiler logs and proposes fixes, with a capped retry loop |
| Verification | Compile, SPIR-V validation, reflection comparison, optional image comparison |
| Explanations | Every change comes with a short reason, which is useful for learning |
| Batch and permutations | Translate a shader with many `#define` variants in one run |
| Offline mode | Run the deterministic pipeline without sending anything to an LLM |

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

## Requirements

- Python 3.11 or newer.
- External tools on your `PATH`: [DXC](https://github.com/microsoft/DirectXShaderCompiler), [SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross) and the [SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools) suite (`spirv-val`, `spirv-opt`). A glslang or glslc binary is needed for GLSL input. `shaderflux doctor` will report what is missing.
- An Anthropic API key (`ANTHROPIC_API_KEY`) for the LLM features, once they exist. It is not needed for offline mode.

## Privacy

Only `translate --repair` talks to the network: when a shader fails to compile it sends that shader, the files it includes and the compiler errors to the Anthropic API. Use `--dry-run` to see exactly what, and read [docs/privacy.md](docs/privacy.md). Everything else (lint, explain, translate without `--repair`) runs entirely on your machine.

## Scope and limitations

- **No proprietary console code.** Shaders written for console SDKs are usually covered by NDAs, so this repository does not include or support console-specific dialects. If you have legitimate access, convert them to plain HLSL first. An adapter interface for that is on the roadmap.
- **"Correct" means verified within limits.** Passing compilation and validation does not prove identical rendering. Image comparison is optional and uses a software rasterizer, which is a testing aid and not a substitute for testing on real GPUs.
- **LLM output can be wrong.** Review the diff and the report before shipping a translated shader.
- **Tool versions matter.** Results depend on the versions of the external compilers. The tool records them in each report.

## Roadmap

- [x] Project idea and scope
- [x] Foundation: repository layout, tooling, packaging (CI configured, not yet observed running)
- [ ] Deterministic conversion pipeline with compiler wrappers (done for GLSL input; HLSL needs DXC verification)
- [x] Analysis: reflection, binding collisions, matrix and intrinsic checks, `lint` and `explain` (DXC-side verification pending)
- [x] LLM repair loop with compiler verification (offline-tested; live API not yet exercised)
- [ ] Command-line tool and first release
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

Contributions are welcome once the foundation lands. Useful early help includes small test shaders with known tricky behaviour, reports of porting problems you have hit, and review of the plan. A `CONTRIBUTING.md` will be added with the foundation work.

## Acknowledgments

ShaderFlux-AI builds on the work of the DXC, SPIRV-Cross, SPIRV-Tools, glslang and Slang projects, among others.

## License

Distributed under the MIT License. Free for open-source use. The license file will be added with the foundation work. Third-party tools keep their own licenses.
