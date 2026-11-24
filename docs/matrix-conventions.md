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

## Not yet verified (needs a real DXC)

These are the open items of plan task 4.3.1. Until they are checked the rules say
"depends on the compiler" rather than stating a default:

- What layout DXC gives an HLSL matrix with **no** qualifier, with and without `-Zpr` / `#pragma pack_matrix`.
- How DXC lowers HLSL `float2x3` to SPIR-V, and whether it matches SPIRV-Cross' reading above.
- Whether `-fvk-use-gl-layout` or similar options change the picture.

Note that published sources disagree on HLSL's default storage ("row-major" in
the Vulkan guide, "column-major" in several forum posts). The disagreement is
partly terminology: storage order, math convention and the order in which
`mul` takes its operands are three different things. That is the reason this
page exists.
