# Tutorial: fix your first shader (10 minutes, no API key)

You have an HLSL shader that works on your platform and you want it to work on PC with Vulkan.
This walks through the loop ShaderFlux-AI is built for: **find the traps, fix the mechanical
ones, check the result.** Nothing here needs an account, a network connection or an API key.

The shader below is `tests/corpus/hlsl/collision.hlsl` from this repository. The output shown
is copied from a real run of the current version.

```hlsl
// b0 and t0 are different HLSL slots but the same Vulkan binding under DXC's default mapping.
cbuffer Params : register(b0)
{
    float4x4 mvp;
    float4 tint;
};

Texture2D albedo : register(t0);
Texture2D normals : register(t1);
SamplerState samp : register(s0);
RWStructuredBuffer<float> output : register(u0);

float4 main(float2 uv : TEXCOORD0) : SV_Target
{
    output[0] = 1.0;
    return albedo.Sample(samp, uv) * tint + normals.Sample(samp, uv);
}
```

## 1. Install and check your tools

```bash
pip install "git+https://github.com/theprexx7676/ShaderFlux-AI.git@v0.1.0"   # not on PyPI yet
shaderflux doctor
```

`doctor` lists which external tools it found and how to install the rest. `lint` and `fix` need
none of them; `--verify` and `translate` need DXC (it ships with the Vulkan SDK).

## 2. Set up the project (optional)

```bash
shaderflux init . --github
```

```text
wrote shaderflux.toml
wrote .github/workflows/lint-shaders.yml
```

This writes a small starter config and a GitHub Actions workflow that lints your shaders on
every pull request. Existing files are never overwritten without `--force`.

## 3. Find the traps

```bash
shaderflux lint lighting.hlsl
```

```text
lighting.hlsl:2  error  BND001  Params (b0), albedo (t0), samp (s0), output (u0)
all map to Vulkan set 0, binding 0: DXC ignores the register type by default
    fix: compile with -fvk-s-shift 3 all -fvk-t-shift 1 all -fvk-u-shift 4 all
(or use [[vk::binding]] attributes)
lighting.hlsl:4  note  MAT002  matrix 'mvp' in a constant buffer has no explicit
row_major/column_major, so its memory layout depends on the compiler's default
packing and flags
    fix: write 'row_major' or 'column_major' on 'mvp' (or add #pragma
pack_matrix) so the layout matches what the CPU uploads

1 error, 1 note in 1 file(s).
```

Why this matters: in HLSL, `b0` and `t0` are different slots. Under DXC's default Vulkan
mapping they all land on **set 0, binding 0**, and the shader misbehaves on the GPU without a
compile error. `shaderflux explain BND001` tells the full story.

## 4. See what the fix would change

```bash
shaderflux fix lighting.hlsl
```

```diff
-    float4x4 mvp;
+    column_major float4x4 mvp;
...
-Texture2D albedo : register(t0);
-Texture2D normals : register(t1);
-SamplerState samp : register(s0);
-RWStructuredBuffer<float> output : register(u0);
+[[vk::binding(1, 0)]] Texture2D albedo : register(t0);
+[[vk::binding(2, 0)]] Texture2D normals : register(t1);
+[[vk::binding(3, 0)]] SamplerState samp : register(s0);
+[[vk::binding(4, 0)]] RWStructuredBuffer<float> output : register(u0);
```

`fix` **only inserts text**, so it never deletes or rewrites your code, and it changes nothing
until you ask. The attributes give each resource its own Vulkan binding; Direct3D builds still
read the `register(...)` and are unaffected. The `column_major` is what DXC already assumed, now
written down so it cannot change under you.

## 5. Apply it

```bash
shaderflux fix lighting.hlsl --write        # or: --out lighting.vk.hlsl
shaderflux lint lighting.hlsl
```

```text
no problems in 1 file(s).
```

## 6. Check it with a real compiler

```bash
shaderflux fix lighting.hlsl --verify --stage fragment
```

`--verify` recompiles the shader with DXC and checks that no two resources share a binding. It
refuses to write a fix that would stop a compiling shader from compiling. Without DXC it says
**not verified** and exits with code 2 instead of pretending. (This step has been run against
two DXC builds on Linux in this project's CI; DXC on Windows is untested.)

## 7. Keep it fixed

Commit the workflow from step 2, or add a one-line check to your own CI:

```bash
shaderflux fix 'shaders/**/*.hlsl' --check     # exit 1 if something can still be fixed
shaderflux lint 'shaders/**/*.hlsl'            # exit 1 on errors
```

## What `fix` will not do

- It fixes only `BND001` and `MAT002`, only in HLSL. Other findings come with a concrete
  suggestion, and `explain` says why.
- It skips what it cannot place safely (for example two resources declared in one statement),
  and says so.
- It does not fix `BND001` when your shader `#include`s other files, because bindings are
  decided across all of them; use the printed `-fvk-*-shift` flags or add the attributes by hand.
- The AI repair mode (`translate --repair`) is optional and experimental, and you never need it
  for any of the steps above.
