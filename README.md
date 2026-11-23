# ShaderFlux-AI

**An open-source assistant for getting shaders running on PC.**

ShaderFlux-AI helps developers who are porting a game or graphics project to PC and are stuck on the shader step. It wraps the standard open-source shader compilers and uses an LLM (Claude) for the parts those tools cannot do: fixing convention mismatches, mapping bindings, replacing missing intrinsics and explaining compiler errors.

> **Status: early planning.** The design is written down, but there is no working code yet. Everything under "Features" is planned, not shipped. See the [roadmap](#roadmap) and the [detailed plan](docs/PLAN.md).

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
| Binding mapping | Maps register/space bindings to descriptor set/binding layouts and back |
| Convention checks | Detects likely matrix-layout and `mul`-order mismatches |
| Error repair | Reads compiler logs and proposes fixes, with a capped retry loop |
| Verification | Compile, SPIR-V validation, reflection comparison, optional image comparison |
| Explanations | Every change comes with a short reason, which is useful for learning |
| Batch and permutations | Translate a shader with many `#define` variants in one run |
| Offline mode | Run the deterministic pipeline without sending anything to an LLM |

## Planned usage

These commands are a design sketch. They do not work yet.

```bash
# Translate a shader
shaderflux translate lighting.hlsl --to glsl --stage fragment

# Fix a shader using a compiler log
shaderflux fix broken.frag --log compiler.log

# Check a shader for known porting risks without changing it
shaderflux lint lighting.hlsl --target vulkan

# Check that the required external tools are installed
shaderflux doctor
```

## Requirements (planned)

- Python 3.11 or newer.
- External tools on your `PATH`: [DXC](https://github.com/microsoft/DirectXShaderCompiler), [SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross) and the [SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools) suite (`spirv-val`, `spirv-opt`). A glslang or glslc binary is needed for GLSL input. `shaderflux doctor` will report what is missing.
- An Anthropic API key (`ANTHROPIC_API_KEY`) for the LLM features. It is not needed for offline mode.

## Privacy

When LLM features are on, shader source and compiler output are sent to the Anthropic API. Do not use them on code you are not allowed to share. Offline mode keeps everything on your machine. Nothing is sent without a configured API key.

## Scope and limitations

- **No proprietary console code.** Shaders written for console SDKs are usually covered by NDAs, so this repository does not include or support console-specific dialects. If you have legitimate access, convert them to plain HLSL first. An adapter interface for that is on the roadmap.
- **"Correct" means verified within limits.** Passing compilation and validation does not prove identical rendering. Image comparison is optional and uses a software rasterizer, which is a testing aid and not a substitute for testing on real GPUs.
- **LLM output can be wrong.** Review the diff and the report before shipping a translated shader.
- **Tool versions matter.** Results depend on the versions of the external compilers. The tool records them in each report.

## Roadmap

- [x] Project idea and scope
- [ ] Foundation: repository layout, tooling, CI
- [ ] Deterministic conversion pipeline with compiler wrappers
- [ ] Analysis: reflection, binding map, matrix-convention checks
- [ ] LLM repair loop with verification
- [ ] Command-line tool and first release
- [ ] Test corpus and benchmarks
- [ ] Batch and permutation support
- [ ] Documentation and tutorials
- [ ] Experimental: render pipeline analysis

The full breakdown, with acceptance criteria, is in [docs/PLAN.md](docs/PLAN.md).

## Contributing

Contributions are welcome once the foundation lands. Useful early help includes small test shaders with known tricky behaviour, reports of porting problems you have hit, and review of the plan. A `CONTRIBUTING.md` will be added with the foundation work.

## Acknowledgments

ShaderFlux-AI builds on the work of the DXC, SPIRV-Cross, SPIRV-Tools, glslang and Slang projects, among others.

## License

Distributed under the MIT License. Free for open-source use. The license file will be added with the foundation work. Third-party tools keep their own licenses.
