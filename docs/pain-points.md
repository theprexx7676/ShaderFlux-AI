# The problems this tool targets

ShaderFlux-AI is built around problems that developers keep running into when
shaders move between HLSL, GLSL and Vulkan. This page lists them with the sources
that describe each one, and says how the tool addresses it.

I did not find a single canonical Stack Overflow thread for these; the evidence
below is official documentation and forum or issue discussions.

## 1. Resources collide on the same Vulkan binding

HLSL numbers resources per register type (`b0`, `t0`, `s0`, `u0` are different
slots). Vulkan has one binding number per descriptor set. DXC's SPIR-V guide says
that by default `register(xN, spaceM)` becomes binding N in set M and **the
register type is ignored, which may cause overlap**. The documented fixes are the
`-fvk-{b|s|t|u}-shift` options or `[[vk::binding]]` attributes, and the two
families of options cannot be combined.

Sources: [DXC SPIR-V guide](https://github.com/microsoft/DirectXShaderCompiler/blob/main/docs/SPIR-V.rst), [LLVM HLSL working group proposal](https://llvm.github.io/wg-hlsl/proposals/0030-vulkan-resource-binding), [Vulkan guide on HLSL](https://docs.vulkan.org/guide/latest/hlsl.html).

*Tool:* rule `BND001` finds the collision and prints the exact shift flags that
remove it, checked collision-free before it is shown.

*Verified:* with DXC 1.9 (CI job `dxc-tests`), the default mapping puts the b0, t0, s0 and u0
resources of `tests/corpus/hlsl/collision.hlsl` on set 0 binding 0, and the printed flags
separate them into bindings 0 to 4. Only the Linux DXC release was exercised.

## 2. Matrices end up transposed

Storage order, math convention and the argument order of `mul` are three separate
things that people mix up. The usual symptom is geometry that is mirrored,
squashed or missing.

Sources: [Vulkan GLSL/HLSL comparison](https://docs.vulkan.org/guide/latest/high_level_shader_language_comparison.html), [Slang matrix layout guide](https://shader-slanggithubio-aidanfnv-wip.readthedocs.io/en/latest/external/slang/docs/user-guide/a1-01-matrix-layout.html), [Matrix operations in shaders](https://sakibsaikia.github.io/graphics/2017/07/06/Matrix-Operations-In-Shaders.html), [a gamedev.net discussion of mul order](https://www.gamedev.net/forums/topic/688396-use-mulvector-matrix-or-mulmatrix-vector-in-hlsl/5341575/), [a Khronos forum port that still failed after reversing mul](https://community.khronos.org/t/glsl-shader-ported-to-hlsl-not-working/110534).

*Tool:* rules `MAT001` to `MAT005`, backed by the experiments in
[matrix-conventions.md](matrix-conventions.md).

## 3. The CPU uploads the matrix in the wrong layout

Even a correct shader breaks when the host writes the matrix transposed. ANGLE's
Vulkan backend had to transpose uniform data for exactly this reason, and a
Dawn thread reports needing an explicit `row_major` after changing the `mul`
order.

Sources: [ANGLE: Vulkan: Fix matrix uniforms](https://chromium.googlesource.com/angle/angle/+/b783fbc799922b43c0988c8686854da85330e679), [Dawn graphics thread](https://groups.google.com/g/dawn-graphics/c/IlVHAsgBwoU).

*Tool:* `MAT002` asks you to state the layout explicitly, so the CPU code has
something definite to match.

## 4. Functions that look the same but are not

`mod` versus `fmod`, `inverse` that HLSL lacks, `round` on halfway values. See
experiment 2 in [matrix-conventions.md](matrix-conventions.md).

*Tool:* rules `INT001` to `INT003`.

## 5. OpenGL GLSL that Vulkan GLSL rejects

A GLSL shader that a desktop OpenGL driver accepts is not necessarily valid Vulkan GLSL.
Four constructs come up again and again when porting: `gl_VertexID` / `gl_InstanceID` (renamed
to `gl_VertexIndex` / `gl_InstanceIndex`), plain `uniform float x;` outside a block, samplers and
images without `layout(binding = N)`, and `in` / `out` variables without `layout(location = N)`.
They already fail when compiled, but the compiler stops at the first one and does not say what to
write instead.

Source: the [GL_KHR_vulkan_glsl](https://github.com/KhronosGroup/GLSL/blob/main/extensions/khr/GL_KHR_vulkan_glsl.txt)
extension.

*Tool:* rules `VKG001` to `VKG004`, each with the replacement to write.

*Verified:* with glslangValidator 15.1.0 (local) and 16.2.0 (CI), each construct is rejected for Vulkan with these
messages: `'gl_VertexID' : undeclared identifier (Did you mean gl_VertexIndex?)`, `'non-opaque
uniforms outside a block' : not allowed when using GLSL for Vulkan`, `'binding' :
sampler/texture/image requires layout(binding=X)`, `'location' : SPIR-V requires location for
user input/output`. A table of 26 snippets is run through both our rules and glslang, and they
agree on every one (`tests/integration/test_vulkan_glsl.py`). Not verified: that
`gl_VertexIndex` differs from `gl_VertexID` for a non-zero base vertex (from the extension text
only).

## Why a tool, not a guide

Each of these has a written explanation somewhere, and developers still lose
days to them because the explanation is only useful after you know which of the
dozen possible causes you have. `shaderflux lint` turns the checklist into a
command, and `shaderflux explain <RULE>` turns each answer into a short,
sourced explanation.
