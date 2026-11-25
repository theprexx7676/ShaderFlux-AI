# Third-party tools and libraries

ShaderFlux-AI does **not** bundle or redistribute any of the tools below. It runs
them as separate programs that the user installs. Each tool keeps its own license.

The licenses below are listed from memory and are **not yet verified**.
Task 1.1.2 / 2.1.2 of [docs/PLAN.md](docs/PLAN.md) requires checking each
license file in the upstream repository before the first release.

| Tool | Purpose | Upstream | License (to verify) |
| --- | --- | --- | --- |
| DirectXShaderCompiler (`dxc`) | HLSL to DXIL / SPIR-V | https://github.com/microsoft/DirectXShaderCompiler | LLVM/NCSA-style (verify) |
| SPIRV-Cross (`spirv-cross`) | SPIR-V to GLSL / HLSL / MSL, reflection | https://github.com/KhronosGroup/SPIRV-Cross | Apache-2.0 (verify) |
| SPIRV-Tools (`spirv-val`, `spirv-opt`, `spirv-dis`, `spirv-as`) | Validation, optimisation, disassembly | https://github.com/KhronosGroup/SPIRV-Tools | Apache-2.0 (verify) |
| glslang (`glslangValidator`) / shaderc (`glslc`) | GLSL to SPIR-V | https://github.com/KhronosGroup/glslang | BSD / Apache-2.0 (verify) |
| Slang (`slangc`), optional, evaluated only | Alternative route | https://github.com/shader-slang/slang | Sources disagree (verify) |

Python dependencies are listed in `pyproject.toml`; their licenses are reported
by `pip-licenses` as part of the pre-release review (plan task 12.3.2).
