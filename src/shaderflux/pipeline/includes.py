"""``#include`` graph construction.

Only a conservative scan is done here: the compilers' own preprocessors remain
the source of truth for what actually gets included. The graph exists to
(1) report missing files and cycles early, (2) decide which files an LLM may
see, and (3) refuse includes that escape the allowed directories.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import Diagnostic, Severity
from shaderflux.core.text import LineIndex
from shaderflux.pipeline.inputs import decode_text

_INCLUDE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*(?P<open>["<])(?P<name>[^">\n]+)[">]', re.M)


@dataclass
class IncludeGraph:
    root: Path
    edges: dict[Path, list[Path]] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def files(self) -> list[Path]:
        """Every file reachable from the root, in depth-first discovery order."""
        order: list[Path] = []

        def visit(node: Path) -> None:
            if node in order:
                return
            order.append(node)
            for child in self.edges.get(node, []):
                visit(child)

        visit(self.root)
        return order

    @property
    def ok(self) -> bool:
        return not any(d.severity is Severity.ERROR for d in self.diagnostics)


def mask_comments(text: str) -> str:
    """Blank out ``//`` and ``/* */`` comments, keeping line numbers intact."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
        elif two == "/*":
            out.append("  ")
            i += 2
            while i < n and text[i : i + 2] != "*/":
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _is_within(path: Path, roots: Sequence[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def build_include_graph(
    root_file: Path,
    include_dirs: Sequence[Path] = (),
    *,
    allowed_roots: Sequence[Path] | None = None,
    max_files: int = 500,
) -> IncludeGraph:
    """Scan ``root_file`` and everything it includes.

    ``allowed_roots`` limits which files may be pulled in. It defaults to the
    root file's directory plus the include directories, so ``#include
    "../../etc/passwd"`` is reported instead of followed.
    """
    root_file = root_file.resolve()
    search = [Path(d).resolve() for d in include_dirs]
    roots = (
        [Path(r).resolve() for r in allowed_roots] if allowed_roots else [root_file.parent, *search]
    )
    graph = IncludeGraph(root=root_file)
    state: dict[Path, str] = {}  # "visiting" | "done"

    def add(severity: Severity, message: str, file: Path, line: int) -> None:
        graph.diagnostics.append(
            Diagnostic(
                severity=severity, message=message, file=str(file), line=line, tool="includes"
            )
        )

    def resolve(kind: str, name: str, includer: Path) -> Path | None:
        candidates = [includer.parent / name] if kind == '"' else []
        candidates += [d / name for d in search]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
        return None

    def visit(path: Path) -> None:
        if len(state) > max_files:
            raise InvalidInputError(f"more than {max_files} included files; giving up")
        state[path] = "visiting"
        graph.edges.setdefault(path, [])
        try:
            text = mask_comments(decode_text(path.read_bytes(), name=path.name))
        except OSError as exc:
            add(Severity.ERROR, f"cannot read file: {exc.strerror or exc}", path, 1)
            state[path] = "done"
            return
        lines = LineIndex(text)
        for match in _INCLUDE.finditer(text):
            line = lines.line_of(match.start())
            name = match.group("name").strip()
            target = resolve(match.group("open"), name, path)
            if target is None:
                add(Severity.ERROR, f"include file not found: {name}", path, line)
                continue
            if not _is_within(target, roots):
                add(
                    Severity.ERROR,
                    f"include {name!r} resolves outside the allowed directories: {target}",
                    path,
                    line,
                )
                continue
            graph.edges[path].append(target)
            status = state.get(target)
            if status == "visiting":
                add(Severity.ERROR, f"include cycle: {path.name} -> {target.name}", path, line)
            elif status is None:
                visit(target)
        state[path] = "done"

    visit(root_file)
    return graph


def flatten(graph: IncludeGraph) -> str:
    """One text view of the shader with each include expanded once.

    Intended for LLM prompts, not for compiling. Markers show where each file
    starts so a model can refer to real file names.
    """
    seen: set[Path] = set()

    def render(path: Path) -> str:
        if path in seen:
            return f"// [shaderflux] {path.name} already included\n"
        seen.add(path)
        raw = decode_text(path.read_bytes(), name=path.name)
        masked = mask_comments(raw)
        pieces = [f"// ===== begin {path.name} =====\n"]
        cursor = 0
        for match in _INCLUDE.finditer(masked):
            pieces.append(raw[cursor : match.start()])
            target = next(
                (t for t in graph.edges.get(path, []) if t.name == Path(match.group("name")).name),
                None,
            )
            pieces.append(render(target) if target else raw[match.start() : match.end()])
            cursor = match.end()
        pieces.append(raw[cursor:])
        pieces.append(f"\n// ===== end {path.name} =====\n")
        return "".join(pieces)

    return render(graph.root)
