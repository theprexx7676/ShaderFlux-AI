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
        "Documented by DXC's SPIR-V guide; the generated flags are still to be checked against a "
        "real dxc (plan task 4.2.4).",
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
        "Qualifier flipping verified with real SPIRV-Cross; behaviour of real DXC on defaults "
        "still to be verified.",
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
