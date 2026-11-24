"""Matrix-convention lint rules (token based, no AST).

Findings are deliberately cautious: this is a heuristic scan, not a type
checker, so each finding carries a confidence level and a concrete suggestion.

What is verified (experiments with real SPIRV-Cross, recorded in
``docs/matrix-conventions.md``): a GLSL column-major matrix becomes an HLSL
``row_major`` matrix with the same offsets, ``M * v`` becomes ``mul(v, M)``, and
``layout(row_major)`` becomes ``column_major``. What is *not* verified yet is how
real DXC treats the same HLSL; those parts are worded as "depends on".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.core.models import Severity, ShaderLanguage
from shaderflux.core.text import LineIndex
from shaderflux.pipeline.includes import mask_comments

_HLSL_MATRIX_DECL = re.compile(
    r"\b(?:(?P<layout>row_major|column_major)\s+)?"
    r"(?:float|half|double|int|uint|bool)(?P<r>[1-4])x(?P<c>[1-4])\s+(?P<name>\w+)"
)
_HLSL_MATRIX_KEYWORD = re.compile(
    r"\b(?:(?P<layout>row_major|column_major)\s+)?matrix(?:\s*<[^>]*>)?\s+(?P<name>\w+)"
)
_GLSL_MATRIX_DECL = re.compile(
    r"\b(?:layout\s*\(\s*(?P<layout>row_major|column_major)\s*\)\s*)?"
    r"d?mat(?P<c>[2-4])(?:x(?P<r>[2-4]))?\s+(?P<name>\w+)"
)
_MUL_CALL = re.compile(r"\bmul\s*\(")
_TRANSPOSE_CALL = re.compile(r"\btranspose\s*\(\s*(?P<arg>[\w.\[\]]+)")
_PACK_PRAGMA = re.compile(r"#\s*pragma\s+pack_matrix\s*\(\s*(row_major|column_major)\s*\)")
_CBUFFER = re.compile(r"\b(?:cbuffer|tbuffer)\s+\w+[^{;]{0,200}\{")
_CONSTANT_BUFFER_T = re.compile(r"\bConstantBuffer\s*<\s*(\w+)\s*>")
_STRUCT = re.compile(r"\bstruct\s+(\w+)\s*\{")
_UNIFORM_BLOCK = re.compile(r"\buniform\s+\w+\s*\{")


@dataclass(frozen=True)
class _Matrix:
    name: str
    layout: str | None
    rows: int | None
    cols: int | None
    line: int
    pos: int


def _brace_pairs(text: str) -> dict[int, int]:
    """Map every ``{`` to its matching ``}`` in a single pass (unmatched ones are absent)."""
    pairs: dict[int, int] = {}
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            pairs[stack.pop()] = i
    return pairs


def _hlsl_matrices(text: str) -> list[_Matrix]:
    found: list[_Matrix] = []
    lines = LineIndex(text)
    for m in _HLSL_MATRIX_DECL.finditer(text):
        found.append(
            _Matrix(
                m["name"],
                m["layout"],
                int(m["r"]),
                int(m["c"]),
                lines.line_of(m.start()),
                m.start(),
            )
        )
    for m in _HLSL_MATRIX_KEYWORD.finditer(text):
        found.append(_Matrix(m["name"], m["layout"], 4, 4, lines.line_of(m.start()), m.start()))
    return found


def _glsl_matrices(text: str) -> list[_Matrix]:
    found: list[_Matrix] = []
    lines = LineIndex(text)
    for m in _GLSL_MATRIX_DECL.finditer(text):
        cols = int(m["c"])
        rows = int(m["r"]) if m["r"] else cols
        found.append(
            _Matrix(m["name"], m["layout"], rows, cols, lines.line_of(m.start()), m.start())
        )
    return found


_MAX_CALL_CHARS = 2000  # a longer argument list is not a real mul() call; stops O(n^2) scans


def _split_args(text: str, open_paren: int) -> list[str] | None:
    """Split the arguments of a call whose ``(`` is at ``open_paren``."""
    depth = 0
    args: list[str] = []
    current: list[str] = []
    for i in range(open_paren, min(len(text), open_paren + _MAX_CALL_CHARS)):
        ch = text[i]
        if ch in "([{":
            depth += 1
            if depth > 1:
                current.append(ch)
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                args.append("".join(current).strip())
                return args
            current.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    return None


def _root_name(arg: str) -> str:
    match = re.match(r"\s*(\w+)", arg)
    return match.group(1) if match else ""


def _is_matrix_expr(arg: str, names: set[str]) -> bool:
    root = _root_name(arg)
    if root in names:
        # ``m[0]`` or ``m._11`` index into the matrix and are not matrices themselves
        rest = arg.strip()[len(root) :].lstrip()
        return not rest.startswith(("[", "."))
    return bool(
        re.match(r"\s*(?:float|half|double)[1-4]x[1-4]\s*\(", arg)
    ) or arg.strip().startswith("transpose(")


def _mul_conventions(text: str, matrix_names: set[str]) -> list[tuple[str, int]]:
    """Classify each ``mul`` call as ``vector-left``, ``matrix-left`` or ``matrix-matrix``."""
    results: list[tuple[str, int]] = []
    lines = LineIndex(text)
    for m in _MUL_CALL.finditer(text):
        args = _split_args(text, m.end() - 1)
        if not args or len(args) != 2:
            continue
        first, second = (_is_matrix_expr(a, matrix_names) for a in args)
        if first and second:
            kind = "matrix-matrix"
        elif second:
            kind = "vector-left"
        elif first:
            kind = "matrix-left"
        else:
            continue
        results.append((kind, lines.line_of(m.start())))
    return results


def _cbuffer_regions(text: str) -> list[tuple[int, int]]:
    """Character ranges holding constant-buffer members (cbuffer and ConstantBuffer<T> bodies)."""
    pairs = _brace_pairs(text)
    regions = [(m.end(), pairs.get(m.end() - 1, len(text))) for m in _CBUFFER.finditer(text)]
    used = {m.group(1) for m in _CONSTANT_BUFFER_T.finditer(text)}
    for m in _STRUCT.finditer(text):
        if m.group(1) in used:
            regions.append((m.end(), pairs.get(m.end() - 1, len(text))))
    return regions


def check_matrices(
    text: str, language: ShaderLanguage, *, file: str | None = None
) -> list[Finding]:
    """Run all matrix rules on one source file."""
    masked = mask_comments(text)
    lines = LineIndex(masked)
    findings: list[Finding] = []

    if language is ShaderLanguage.HLSL:
        matrices = _hlsl_matrices(masked)
        names = {m.name for m in matrices}
        conventions = _mul_conventions(masked, names)

        vector_calls = [(kind, line) for kind, line in conventions if kind != "matrix-matrix"]
        if len({kind for kind, _ in vector_calls}) > 1:
            first_kind = vector_calls[0][0]
            minority_line = next(line for kind, line in vector_calls if kind != first_kind)
            findings.append(
                Finding(
                    rule="MAT001",
                    severity=Severity.WARNING,
                    message=(
                        "mul() is used with the vector on the left in some places and on the right "
                        "in others; a matrix can only be right for one of them"
                    ),
                    file=file,
                    line=minority_line,
                    confidence=Confidence.MEDIUM,
                    suggestion=(
                        "pick one convention (usually mul(vector, matrix) for row vectors) and "
                        "transpose the matrices on the host side to match"
                    ),
                )
            )

        has_pragma = bool(_PACK_PRAGMA.search(masked))
        regions = _cbuffer_regions(masked)
        in_buffer = [m for m in matrices if any(lo <= m.pos < hi for lo, hi in regions)]
        if not has_pragma:
            for matrix in in_buffer:
                if matrix.layout is None:
                    findings.append(
                        Finding(
                            rule="MAT002",
                            severity=Severity.NOTE,
                            message=(
                                f"matrix '{matrix.name}' in a constant buffer has no explicit "
                                "row_major/column_major, so its memory layout depends on the "
                                "compiler's default packing and flags"
                            ),
                            file=file,
                            line=matrix.line,
                            confidence=Confidence.MEDIUM,
                            suggestion=(
                                f"write 'row_major' or 'column_major' on '{matrix.name}' (or add "
                                "#pragma pack_matrix) so the layout matches what the CPU uploads"
                            ),
                        )
                    )

        buffer_names = {m.name for m in in_buffer}
        for m in _TRANSPOSE_CALL.finditer(masked):
            if _root_name(m["arg"]) in buffer_names:
                findings.append(
                    Finding(
                        rule="MAT003",
                        severity=Severity.NOTE,
                        message=(
                            f"transpose() on constant-buffer matrix '{_root_name(m['arg'])}' "
                            "is often a workaround for a layout mismatch"
                        ),
                        file=file,
                        line=lines.line_of(m.start()),
                        confidence=Confidence.LOW,
                        suggestion="fix the layout at upload or declaration, not with transpose()",
                    )
                )

        for matrix in matrices:
            if matrix.rows != matrix.cols and matrix.rows is not None:
                findings.append(_non_square(matrix, "HLSL floatRxC is rows x columns", file))
        return findings

    if language is ShaderLanguage.GLSL:
        for matrix in _glsl_matrices(masked):
            if matrix.rows != matrix.cols and matrix.rows is not None:
                findings.append(_non_square(matrix, "GLSL matCxR is columns x rows", file))
            if matrix.layout == "row_major":
                findings.append(
                    Finding(
                        rule="MAT005",
                        severity=Severity.NOTE,
                        message=(
                            f"'{matrix.name}' is row_major, the opposite of GLSL's default; "
                            "translators flip qualifiers, so the CPU upload must match"
                        ),
                        file=file,
                        line=matrix.line,
                        confidence=Confidence.MEDIUM,
                        suggestion="check the host-side matrix upload against this qualifier",
                    )
                )
    return findings


def _non_square(matrix: _Matrix, convention: str, file: str | None) -> Finding:
    return Finding(
        rule="MAT004",
        severity=Severity.NOTE,
        message=(
            f"non-square matrix '{matrix.name}' ({matrix.rows}x{matrix.cols}): {convention}, "
            "the opposite order of the other language"
        ),
        file=file,
        line=matrix.line,
        confidence=Confidence.LOW,
        suggestion="when hand-porting, double-check which dimension you meant",
    )
