"""The layering of the code, checked by reading the imports.

``docs/architecture.md`` describes these layers. This test keeps the code and that description
from drifting apart: a new import that breaks the layering fails here, with the file named.
"""

from __future__ import annotations

import ast
import re
import tomllib
from collections import defaultdict
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "shaderflux"

# package -> the packages it may import (from the same project), bottom layer first.
ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "source": {"core"},
    "tools": {"core"},
    "verify": {"core", "tools"},
    "analysis": {"core", "source", "tools"},
    "pipeline": {"core", "source", "tools", "verify"},
    "llm": {"core", "source", "tools", "pipeline"},
    "reporting": {"core", "analysis", "llm", "verify"},
    "workflows": {
        "core",
        "source",
        "tools",
        "verify",
        "analysis",
        "pipeline",
        "llm",
        "reporting",
    },
    "cli": {
        "core",
        "source",
        "tools",
        "verify",
        "analysis",
        "pipeline",
        "llm",
        "reporting",
        "workflows",
    },
}
TOP = "(top)"  # shaderflux/__init__.py, which only provides __version__
MAIN = "(main)"  # shaderflux/__main__.py, the `python -m shaderflux` entry point
API = "(api)"  # shaderflux/api.py, the public Python API: may import any library layer


def imports_of(path: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def package_of(path: Path) -> str:
    parts = path.relative_to(SRC).parts
    if len(parts) > 1:
        return parts[0]
    return {"__main__.py": MAIN, "api.py": API}.get(parts[0], TOP)


def project_edges() -> dict[str, dict[str, list[str]]]:
    """package -> imported package -> the files that import it."""
    edges: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for path in sorted(SRC.rglob("*.py")):
        pkg = package_of(path)
        for module in imports_of(path):
            parts = module.split(".")
            if parts[0] != "shaderflux":
                continue
            dep = parts[1] if len(parts) > 1 else TOP
            if dep != pkg:
                edges[pkg][dep].append(str(path.relative_to(SRC)))
    return edges


def test_every_package_is_listed() -> None:
    on_disk = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    assert on_disk == set(ALLOWED), (
        "a package was added or removed: update ALLOWED here and docs/architecture.md"
    )


def test_imports_respect_the_layers() -> None:
    violations = []
    for pkg, deps in project_edges().items():
        if pkg in {TOP, MAIN, API}:
            continue
        for dep, files in deps.items():
            if dep != TOP and dep not in ALLOWED[pkg]:
                violations.append(f"{pkg} must not import {dep}: {sorted(set(files))}")
    assert not violations, "\n".join(violations)


def test_only_the_entry_point_imports_the_cli() -> None:
    importers = {pkg for pkg, deps in project_edges().items() if "cli" in deps}
    assert importers <= {MAIN}, importers  # shaderflux/__main__.py only


def test_the_public_api_does_not_reach_into_the_cli() -> None:
    assert "cli" not in project_edges()[API]


def test_there_are_no_import_cycles() -> None:
    edges = {pkg: set(deps) for pkg, deps in project_edges().items()}

    def reachable(start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            for nxt in edges.get(stack.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    cycles = [pkg for pkg in edges if pkg in reachable(pkg)]
    assert not cycles, f"import cycle through: {cycles}"


@pytest.mark.parametrize(
    ("module", "only_in"),
    [
        ("subprocess", {"tools/runner.py"}),  # every external tool runs through the runner
        ("anthropic", {"llm/anthropic_provider.py"}),  # one place talks to the API
    ],
)
def test_risky_modules_are_imported_in_exactly_one_place(module: str, only_in: set[str]) -> None:
    users = {
        str(p.relative_to(SRC)).replace("\\", "/")
        for p in SRC.rglob("*.py")
        if any(m == module or m.startswith(module + ".") for m in imports_of(p))
    }
    assert users == only_in


def test_user_interface_libraries_stay_in_the_cli() -> None:
    offenders = sorted(
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if package_of(p) != "cli"
        and any(m.split(".")[0] in {"typer", "rich"} for m in imports_of(p))
    )
    assert not offenders, f"library code must not depend on the UI: {offenders}"


def test_library_code_never_prints() -> None:
    """Output belongs to the cli package; everything else returns data."""
    offenders = []
    for path in SRC.rglob("*.py"):
        if package_of(path) in {"cli", TOP, MAIN}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, offenders


# ---- lint rule ids: the code and the documentation must agree ---------------------------------

RULE_ID = re.compile(r"""rule\s*=\s*["']([A-Z]{3}\d{3})["']""")


def emitted_rule_ids() -> set[str]:
    ids: set[str] = set()
    for path in SRC.rglob("*.py"):
        if path.name == "rules.py":
            continue
        ids.update(RULE_ID.findall(path.read_text(encoding="utf-8")))
    data = tomllib.loads((SRC / "analysis" / "data" / "intrinsics.toml").read_text("utf-8"))
    ids.update(entry["rule"] for entry in data["intrinsic"] if entry.get("rule"))
    return ids


def test_every_rule_the_code_can_emit_is_documented() -> None:
    from shaderflux.analysis.rules import all_rules

    undocumented = emitted_rule_ids() - set(all_rules())
    assert not undocumented, f"add these to analysis/rules.py: {sorted(undocumented)}"


def test_every_documented_rule_is_emitted_somewhere() -> None:
    from shaderflux.analysis.rules import all_rules

    stale = set(all_rules()) - emitted_rule_ids()
    assert not stale, f"documented but never emitted: {sorted(stale)}"
