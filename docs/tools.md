# External tools

ShaderFlux-AI runs these programs; it does not bundle them. Run
`shaderflux doctor` to see what is installed on your machine.

| Tool | Used for | Required? |
| --- | --- | --- |
| `dxc` | HLSL to SPIR-V and DXIL | Yes, for HLSL input |
| `spirv-cross` | SPIR-V to GLSL / HLSL / MSL, reflection | Yes |
| `spirv-val` | SPIR-V validation | Yes |
| `spirv-dis`, `spirv-opt` | Readable diffs, optional optimisation | No |
| `glslangValidator` or `glslc` | GLSL to SPIR-V | One of them, for GLSL input |

Override the location of a tool with `SHADERFLUX_<TOOL>` (for example
`SHADERFLUX_DXC=/opt/dxc/bin/dxc`), or put it on `PATH`, or set `VULKAN_SDK`.

## Observations from development (Linux, Ubuntu 24.04 packages)

Recorded because they affect users and CI:

- `spirv-tools` 2025.1, `glslang-tools` 15.1.0 and `glslc` 2023.8 installed from
  the distribution and worked with the test-suite.
- The distribution's `spirv-cross` is a **2021 build** and has no `--version`
  flag, so `doctor` reports its version as unknown. Newer SPIRV-Cross builds
  should be preferred; plan task 2.1.4 decides how CI obtains one.
- `dxc` is not packaged by the distribution. The Vulkan SDK from LunarG includes
  it. **The DXC backend has therefore not yet been run against a real `dxc`.**
  Its unit tests use a fake executable, and `tests/integration/test_dxc.py` will
  exercise the real one as soon as it is available.
- Tools disagree on option syntax: `spirv-val` wants `--target-env <env>` (a
  separate argument) while `spirv-opt` wants `--target-env=<env>`, and
  SPIRV-Tools spells environments `spv1.5` where glslang and DXC use `spirv1.5`.
  The backends handle this; tests cover it.

## Still to verify (plan tasks 2.1.2 and 2.1.3)

- The license of each tool, from its upstream `LICENSE` file.
- Maintenance status of each tool (latest release, recent commits). The evidence
  gathered so far was inconclusive for SPIRV-Cross and ShaderConductor, so no
  claim is made either way.
