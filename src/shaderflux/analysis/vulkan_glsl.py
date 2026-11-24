"""Rules for GLSL that is going to Vulkan (``VKG001`` to ``VKG004``).

Desktop OpenGL GLSL is accepted by a driver, but the Vulkan flavour of GLSL is stricter. Each
rule below is a construct that glslang (the reference compiler) rejects for Vulkan; the exact
glslang messages were observed with glslangValidator 15.1.0 and are recorded in
``docs/pain-points.md`` and in ``tests/integration/test_vulkan_glsl.py``.

The scanner is token based and linear in the size of the input: it splits the text into
top-level declarations (the text before a ``;`` or ``{`` outside any braces or parentheses) and
looks only at those, never inside function bodies.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.core.models import Severity
from shaderflux.core.text import LineIndex
from shaderflux.source.includes import mask_comments

_MAX_DECLARATION_CHARS = 2000  # a longer "declaration" is not one; also bounds the work per item
_VERTEX_BUILTINS = {"gl_VertexID": "gl_VertexIndex", "gl_InstanceID": "gl_InstanceIndex"}
_BUILTIN_USE = re.compile(r"\bgl_(?:VertexID|InstanceID)\b")
_WORD = re.compile(r"[A-Za-z_]\w*")
_OPAQUE_PREFIXES = (
    "sampler", "isampler", "usampler", "texture", "itexture", "utexture",
    "image", "iimage", "uimage", "subpass", "isubpass", "usubpass",
    "atomic_uint", "accelerationStructure",
)  # fmt: skip
_QUALIFIERS = frozenset(
    {
        *("highp", "mediump", "lowp", "flat", "smooth", "noperspective", "centroid", "sample"),
        *("const", "coherent", "volatile", "restrict", "readonly", "writeonly", "invariant"),
        *("precise", "patch"),
    }
)
_STORAGE = frozenset({"uniform", "in", "out"})


@dataclass(frozen=True)
class _Declaration:
    head: str  # the text before the ';' or '{', layout(...) groups included
    start: int
    is_block: bool  # ended by '{' (a uniform/in/out block, a struct, or a function body)


def _declarations(masked: str) -> Iterator[_Declaration]:
    """Top-level declarations of ``masked`` (comments already blanked)."""
    n = len(masked)
    i = start = 0
    parens = 0
    at_line_start = True
    while i < n:
        c = masked[i]
        if c == "\n":
            at_line_start = True
            i += 1
            continue
        if c == "#" and at_line_start:  # a preprocessor line never joins a declaration
            end = masked.find("\n", i)
            i = n if end == -1 else end
            start = i
            continue
        if not c.isspace():
            at_line_start = False
        if c == "(":
            parens += 1
        elif c == ")":
            parens = max(0, parens - 1)
        elif parens == 0 and c == ";":
            if i - start <= _MAX_DECLARATION_CHARS:
                yield _Declaration(masked[start:i], start, False)
            start = i + 1
        elif parens == 0 and c == "{":
            if i - start <= _MAX_DECLARATION_CHARS:
                yield _Declaration(masked[start:i], start, True)
            depth = 1
            i += 1
            while i < n and depth:
                depth += (masked[i] == "{") - (masked[i] == "}")
                i += 1
            start = i
            continue
        elif c == "}":
            start = i + 1
        i += 1


def _split_layouts(head: str) -> tuple[str, list[str]]:
    """Remove ``layout(...)`` groups from ``head``; return the rest and the group contents."""
    rest: list[str] = []
    groups: list[str] = []
    pos = 0
    for match in re.finditer(r"\blayout\b", head):
        if match.start() < pos:
            continue
        j = match.end()
        while j < len(head) and head[j].isspace():
            j += 1
        if j >= len(head) or head[j] != "(":
            continue
        depth = 0
        k = j
        while k < len(head):
            depth += (head[k] == "(") - (head[k] == ")")
            k += 1
            if depth == 0:
                break
        rest.append(head[pos : match.start()])
        groups.append(head[j + 1 : k - 1])
        rest.append(" ")
        pos = k
    rest.append(head[pos:])
    return "".join(rest), groups


def _has_layout_key(groups: list[str], key: str) -> bool:
    return any(key in re.findall(r"[A-Za-z_]\w*", g) for g in groups)


def _is_opaque(type_name: str) -> bool:
    return type_name.startswith(_OPAQUE_PREFIXES)


def check_vulkan_glsl(text: str, *, file: str | None = None) -> list[Finding]:
    """Report GLSL constructs that Vulkan GLSL (glslang) rejects."""
    masked = mask_comments(text)
    lines = LineIndex(masked)
    # Conditional compilation may hide the other branch, so a finding may be a false alarm.
    confidence = (
        Confidence.MEDIUM if re.search(r"^[ \t]*#[ \t]*if", masked, re.M) else Confidence.HIGH
    )
    findings: list[Finding] = []

    for match in _BUILTIN_USE.finditer(masked):
        old = match.group(0)
        new = _VERTEX_BUILTINS[old]
        findings.append(
            Finding(
                rule="VKG001",
                severity=Severity.ERROR,
                message=f"{old} does not exist in Vulkan GLSL (glslang: undeclared identifier)",
                file=file,
                line=lines.line_of(match.start()),
                confidence=confidence,
                suggestion=(
                    f"use {new}. VERIFY: it counts from the base "
                    "vertex/instance given to the draw call, so it can differ from "
                    f"{old} when those are not zero"
                ),
            )
        )

    for decl in _declarations(masked):
        rest, groups = _split_layouts(decl.head)
        if "(" in rest:  # a function prototype or definition
            continue
        words = _WORD.findall(rest)
        storage = next((w for w in words if w in _STORAGE), None)
        if storage is None:
            continue
        remaining = [w for w in words if w not in _STORAGE and w not in _QUALIFIERS]
        if not remaining:  # e.g. layout(local_size_x = 8) in;
            continue
        type_name = remaining[0]
        name = remaining[1] if len(remaining) > 1 else type_name
        if type_name.startswith("gl_"):  # gl_PerVertex and friends
            continue
        line = lines.line_of(decl.start + (len(decl.head) - len(decl.head.lstrip())))
        if storage == "uniform":
            if decl.is_block:
                continue
            if _is_opaque(type_name):
                if type_name.startswith("subpass") or _has_layout_key(groups, "binding"):
                    continue
                findings.append(
                    Finding(
                        rule="VKG003",
                        severity=Severity.ERROR,
                        message=(
                            f"'{name}' ({type_name}) needs an explicit binding in "
                            "Vulkan GLSL (glslang: sampler/texture/image requires "
                            "layout(binding=X))"
                        ),
                        file=file,
                        line=line,
                        confidence=confidence,
                        suggestion=(
                            f"write layout(set = 0, binding = N) uniform {type_name} "
                            f"{name};  with an N that no other resource in the set uses"
                        ),
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule="VKG002",
                        severity=Severity.ERROR,
                        message=(
                            f"uniform '{name}' is outside a block, which Vulkan GLSL "
                            "does not allow (glslang: non-opaque uniforms outside a block)"
                        ),
                        file=file,
                        line=line,
                        confidence=confidence,
                        suggestion=(
                            "move it into a block: layout(set = 0, binding = N) uniform "
                            f"Params {{ {type_name} {name}; }};  or use a push-constant "
                            "block"
                        ),
                    )
                )
        elif not _has_layout_key(groups, "location"):
            what = f"'{name}'" if not decl.is_block else f"block '{type_name}'"
            findings.append(
                Finding(
                    rule="VKG004",
                    severity=Severity.ERROR,
                    message=(
                        f"{storage} {what} has no layout(location = N), which Vulkan GLSL "
                        "requires (glslang: SPIR-V requires location for user input/output)"
                    ),
                    file=file,
                    line=line,
                    confidence=confidence,
                    suggestion=(
                        f"write layout(location = N) {storage} ...; with locations that match "
                        "the other stage (or the vertex buffer layout)"
                    ),
                )
            )
    return findings
