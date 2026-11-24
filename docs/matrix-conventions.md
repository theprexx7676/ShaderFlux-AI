# Matrix conventions: what we verified

Matrix handling is the most common silent bug when porting shaders. This page
records **experiments run with real tools**, so the lint rules (`MAT001` to
`MAT005`) rest on evidence rather than memory.

Tool used: SPIRV-Cross (Ubuntu 24.04 package, a 2021 build) fed with SPIR-V from
glslangValidator 15.1.0. Reproduce with `tests/corpus/glsl/matrices.vert`.

## Experiment 1: GLSL to HLSL via SPIR-V

Input (GLSL, std140 uniform block):

```glsl
layout(set=0,binding=0,std140) uniform U {
    mat4 colMajor;                      // default layout
    layout(row_major) mat4 rowMajor;    // explicit
    mat2x3 rect;                        // 2 columns, 3 rows
} u;
gl_Position  = u.colMajor * p;          // matrix * vector
gl_Position += p * u.colMajor;          // vector * matrix
gl_Position += u.rowMajor * p;
vec3 r = u.rect * vec2(1.0, 2.0);
```

Output (HLSL):

```hlsl
cbuffer U : register(b0)
{
    row_major float4x4 u_colMajor : packoffset(c0);
    column_major float4x4 u_rowMajor : packoffset(c4);
    row_major float2x3 u_rect : packoffset(c8);
};
gl_Position = mul(p, u_colMajor);          // from  colMajor * p
gl_Position += mul(u_colMajor, p);         // from  p * colMajor
gl_Position += mul(p, u_rowMajor);         // from  rowMajor * p
float3 r = mul(float2(1.0f, 2.0f), u_rect);
```

| Observation | Evidence |
| --- | --- |
| Memory layout is preserved: offsets and strides are identical on both sides | reflection shows `offset` 0 / 64 / 128 and `matrix_stride` 16 for all three |
| The layout **qualifier is flipped**: GLSL default (column-major) becomes HLSL `row_major`, and GLSL `row_major` becomes HLSL `column_major` | cbuffer above |
| The **operand order of multiplication is swapped**: `M * v` becomes `mul(v, M)` | statements above |
| Non-square matrices keep the same digits (`mat2x3` becomes `float2x3`), but the two languages read the digits in opposite orders (GLSL: columns x rows; HLSL: rows x columns) | declaration above |

Consequence: a *translator* gets this right. A *human porting by hand* has to
flip three things at once (qualifier, operand order, dimension reading), and
forgetting one produces a shader that compiles but draws garbage. That is what
rules `MAT001`, `MAT002`, `MAT004` and `MAT005` look for.

## Experiment 2: functions that are not plain renames

| GLSL | HLSL output | Meaning |
| --- | --- | --- |
| `mod(x, y)` | helper `x - y * floor(x / y)` | GLSL `mod` floors, so it needs a helper (HLSL `fmod` truncates). Rule `INT001` |
| `inverse(m)` | generated `spvInverse` helper, dozens of lines | HLSL has no `inverse`. Rule `INT002` |
| `gl_VertexIndex` | `SV_VertexID` | input semantic mapping |

## Experiment 3: DXC 1.9 (HLSL to SPIR-V), run in CI

Tool: DXC `1.9(5512-01b62ad4)(1.9.2609.5)` from Microsoft's Linux release, then SPIRV-Cross
reflection. Reproduce with `scripts/dxc_experiments.py` (CI job `dxc-tests`).

Input: a constant buffer with `float4x4 plain;`, `row_major float4x4 rowm;`,
`column_major float4x4 colm;` and `float2x3 rect;`.

| DXC flags | `plain` | `rowm` | `colm` | `rect` | offsets |
| --- | --- | --- | --- | --- | --- |
| none | like `colm` | other | like `plain` | like `plain` | 0, 64, 128, 192 |
| `-Zpr` | like `rowm` | like `plain` | other | like `plain` | 0, 64, 128, 192 |
| `-Zpc` | like `colm` | other | like `plain` | like `plain` | 0, 64, 128, 192 |

("like" means the same decoration in the SPIR-V that DXC wrote, as reflected by SPIRV-Cross.)

| Observation | Meaning |
| --- | --- |
| An unqualified matrix in a constant buffer behaves exactly like `column_major` | HLSL's default packing is **column-major** with DXC. Verified, not assumed |
| `-Zpr` makes unqualified matrices behave like `row_major`; `-Zpc` equals the default | The compiler flag flips every unqualified matrix at once |
| Offsets and strides are identical in every variant | Only the interpretation of the bytes changes, which is why a mismatch compiles fine and draws garbage |
| In the SPIR-V, HLSL `column_major` carries the `RowMajor` decoration and HLSL `row_major` carries none | The qualifier flips between HLSL and SPIR-V, as it does between GLSL and HLSL in experiment 1 |
| `float2x3` becomes `mat2x3`: same digits | The digits are kept; the reading order differs between GLSL and HLSL (rule `MAT004`) |

Also checked with the same DXC (all passing in `tests/integration/test_dxc.py`):

- the binding collision of `BND001` is real: by default `Params`, `albedo`, `samp` and `output` all land on set 0, binding 0;
- the flags that `shaderflux lint` prints (`-fvk-s-shift 3 all -fvk-t-shift 1 all -fvk-u-shift 4 all`) put them on bindings 0, 1, 2, 3 and 4;
- the HLSL that SPIRV-Cross generates (Shader Model 5) is accepted by DXC both as SPIR-V and as DXIL.

A bug this found: without `--shader-model`, SPIRV-Cross writes Shader Model 3 HLSL (`sampler2D`,
`tex2D`, `COLOR0`), which DXC rejects. ShaderFlux-AI now defaults to Shader Model 5.0.

## Still not verified

- Whether `#pragma pack_matrix(row_major)` behaves like `-Zpr` (a test for it is in `tests/integration/test_dxc.py`; read its result in CI before relying on it).
- Options such as `-fvk-use-gl-layout` and `-fvk-use-dx-layout`.
- Other DXC versions, and the Windows build of DXC (the one most developers have). Only the Linux 1.9 release was exercised.

Note that published sources disagree on HLSL's default storage ("row-major" in the Vulkan guide,
"column-major" in several forum posts). The disagreement is partly terminology: storage order,
math convention and the order in which `mul` takes its operands are three different things. The
experiments above settle the storage question for DXC.
