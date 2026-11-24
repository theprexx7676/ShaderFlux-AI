"""Human-readable documentation for every lint rule (``shaderflux explain``)."""

from __future__ import annotations

from dataclasses import dataclass, field

from shaderflux.analysis.intrinsics import load_intrinsics


@dataclass(frozen=True)
class RuleInfo:
    id: str
    title: str
    why: str
    fix: str
    evidence: str  # how the claim was established
    links: tuple[str, ...] = field(default_factory=tuple)


_DXC_DOC = "https://github.com/microsoft/DirectXShaderCompiler/blob/main/docs/SPIR-V.rst"
_VULKAN_CMP = "https://docs.vulkan.org/guide/latest/high_level_shader_language_comparison.html"
_SLANG_MATRIX = (
    "https://shader-slanggithubio-aidanfnv-wip.readthedocs.io/en/latest/external/slang/docs/"
    "user-guide/a1-01-matrix-layout.html"
)

_BASE: tuple[RuleInfo, ...] = (
    RuleInfo(
        "BND001",
        "Resources collide on the same Vulkan binding",
        "HLSL numbers resources separately for each register type, so b0, t0, s0 and u0 are four "
        "different slots. Vulkan has a single binding number per descriptor set. By default DXC "
        "maps register(xN, spaceM) to set M, binding N and ignores the register type, so a "
        "constant buffer on b0 and a texture on t0 end up on the same binding.",
        "Give each register type its own range with -fvk-b-shift / -fvk-t-shift / -fvk-s-shift / "
        "-fvk-u-shift (shaderflux prints the exact flags), or pin each resource with "
        "[[vk::binding(binding, set)]].",
        "Documented by DXC's SPIR-V guide and confirmed with DXC 1.9 in CI: by default these "
        "resources land on one binding, and the printed flags separate them "
        "(tests/integration/test_dxc.py).",
        (_DXC_DOC,),
    ),
    RuleInfo(
        "BND002",
        "Explicit [[vk::binding]] attributes clash",
        "Two resources were pinned to the same (binding, set) with [[vk::binding]]. Shift flags "
        "cannot fix this because the attribute wins over them.",
        "Give each attribute a distinct (binding, set).",
        "Follows directly from the source.",
        (_DXC_DOC,),
    ),
    RuleInfo(
        "VKG001",
        "gl_VertexID / gl_InstanceID do not exist in Vulkan GLSL",
        "Vulkan GLSL replaces these OpenGL built-ins with gl_VertexIndex and gl_InstanceIndex. "
        "glslang reports the old names as undeclared identifiers when compiling for Vulkan.",
        "Rename to gl_VertexIndex / gl_InstanceIndex. The new built-ins count from the base "
        "vertex/instance of the draw call, so check shaders that draw with a non-zero base.",
        "Confirmed with glslangValidator 15.1.0 and 16.2.0 "
        "(tests/integration/test_vulkan_glsl.py): the old name is rejected for Vulkan, the new "
        "name compiles. The base-vertex difference is from the GL_KHR_vulkan_glsl description "
        "and has not been run here (VERIFY).",
        ("https://github.com/KhronosGroup/GLSL/blob/main/extensions/khr/GL_KHR_vulkan_glsl.txt",),
    ),
    RuleInfo(
        "VKG002",
        "Uniform outside a block",
        "OpenGL lets a shader declare a plain `uniform float gain;`. Vulkan has no loose "
        "uniforms: values must live in a uniform block (a buffer) or a push-constant block.",
        "Put the value into a block: layout(set = 0, binding = N) uniform Params { float gain; }; "
        "and update it through a buffer instead of glUniform.",
        "Confirmed with glslangValidator 15.1.0 and 16.2.0 "
        "(tests/integration/test_vulkan_glsl.py): "
        "'non-opaque uniforms outside a block : not allowed when using GLSL for Vulkan'.",
        ("https://github.com/KhronosGroup/GLSL/blob/main/extensions/khr/GL_KHR_vulkan_glsl.txt",),
    ),
    RuleInfo(
        "VKG003",
        "Sampler, texture or image without a binding",
        "OpenGL assigns sampler bindings from the CPU side. Vulkan GLSL needs "
        "layout(binding = N) (and optionally set) in the shader itself.",
        "Write layout(set = 0, binding = N) uniform sampler2D tex; with an N that is unique "
        "in the set.",
        "Confirmed with glslangValidator 15.1.0 and 16.2.0 "
        "(tests/integration/test_vulkan_glsl.py): "
        "'sampler/texture/image requires layout(binding=X)'.",
        ("https://github.com/KhronosGroup/GLSL/blob/main/extensions/khr/GL_KHR_vulkan_glsl.txt",),
    ),
    RuleInfo(
        "VKG004",
        "Shader input or output without a location",
        "OpenGL links stage inputs and outputs by name. Vulkan links them by "
        "layout(location = N), and glslang refuses user inputs and outputs without one.",
        "Add layout(location = N) to every `in` and `out` (user variables and interface "
        "blocks), with matching numbers in the neighbouring stage or the vertex layout.",
        "Confirmed with glslangValidator 15.1.0 and 16.2.0 "
        "(tests/integration/test_vulkan_glsl.py): "
        "'SPIR-V requires location for user input/output'.",
        ("https://github.com/KhronosGroup/GLSL/blob/main/extensions/khr/GL_KHR_vulkan_glsl.txt",),
    ),
    RuleInfo(
        "LNT001",
        "File too large or too long-lined to analyse",
        "The lint rules scan source text with pattern matching. To make sure a huge or "
        "hostile file can never stall a build, files over 2,000,000 characters or with a "
        "line over 20,000 characters are skipped, and this warning says so.",
        "Split the file, or lint the hand-written source instead of generated output.",
        "A fixed safety limit, not a judgement about the shader.",
        (),
    ),
    RuleInfo(
        "INC001",
        "Include problem",
        "An #include could not be resolved: the file is missing, the includes form a cycle, "
        "or the path resolves outside the allowed directories.",
        "Fix the path, break the cycle, or pass the directory with -I.",
        "Follows directly from the source and the file system.",
        (),
    ),
    RuleInfo(
        "MAT001",
        "mul() is used with both operand orders",
        "mul(v, M) treats v as a row vector and mul(M, v) as a column vector, so the same matrix "
        "cannot be right for both. A shader that mixes them is usually compensating for a "
        "transposed matrix somewhere.",
        "Pick one convention for the whole shader and transpose the matrices on the CPU side to "
        "match.",
        "Heuristic scan of mul() calls. Matrix-vs-vector is guessed from declarations, so check "
        "the reported line.",
        (_SLANG_MATRIX, _VULKAN_CMP),
    ),
    RuleInfo(
        "MAT002",
        "Constant-buffer matrix has no explicit layout",
        "Without row_major or column_major, a matrix's memory layout depends on compiler defaults "
        "and flags, and the CPU must upload data in the same layout. When a shader is translated "
        "the qualifier can also flip: SPIRV-Cross turned a default GLSL matrix into an HLSL "
        "row_major matrix with identical memory offsets.",
        "Write row_major or column_major on the matrix (or use #pragma pack_matrix) so the layout "
        "is stated in the source.",
        "Verified with real tools: SPIRV-Cross flips the qualifier between GLSL and HLSL, and with "
        "DXC 1.9 an unqualified matrix is packed like column_major while -Zpr or "
        "#pragma pack_matrix(row_major) makes it row_major (docs/matrix-conventions.md).",
        (_SLANG_MATRIX,),
    ),
    RuleInfo(
        "MAT003",
        "transpose() on a constant-buffer matrix",
        "transpose() applied to a matrix that comes from a constant buffer is often a workaround "
        "for an upload or layout mismatch, and it costs work in every invocation.",
        "Fix the layout where the data is uploaded or declared.",
        "Low-confidence heuristic.",
        (),
    ),
    RuleInfo(
        "MAT004",
        "Non-square matrix dimensions are written in opposite orders",
        "GLSL names matrices by columns x rows (mat2x3 has 2 columns, 3 rows) while HLSL names "
        "them rows x columns. When porting a non-square matrix by hand it is easy to swap them.",
        "Check which dimension you meant on each side, and test with a known transform.",
        "Language definitions; low-confidence heuristic.",
        (_VULKAN_CMP,),
    ),
    RuleInfo(
        "MAT005",
        "row_major qualifier will be flipped by translation",
        "row_major is the opposite of GLSL's default. SPIRV-Cross translated GLSL row_major to "
        "HLSL column_major, keeping the memory identical.",
        "Make sure the CPU upload matches the layout you declared.",
        "Verified with real SPIRV-Cross.",
        (),
    ),
)


def _intrinsic_rules() -> tuple[RuleInfo, ...]:
    rules = []
    for entry in load_intrinsics():
        if entry.flag and entry.rule:
            rules.append(
                RuleInfo(
                    entry.rule,
                    entry.title or entry.rule,
                    entry.note or "",
                    entry.fix or "",
                    f"Evidence level: {entry.evidence}.",
                    (),
                )
            )
    return tuple(rules)


def all_rules() -> dict[str, RuleInfo]:
    return {rule.id: rule for rule in (*_BASE, *_intrinsic_rules())}


def get_rule(rule_id: str) -> RuleInfo | None:
    return all_rules().get(rule_id.upper())
