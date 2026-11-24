"""Tests for include graph construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import Severity
from shaderflux.source.includes import build_include_graph, flatten, mask_comments

pytestmark = pytest.mark.unit


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_mask_comments_keeps_line_numbers() -> None:
    text = 'a // #include "x"\n/* #include "y"\n more */ b\n'
    masked = mask_comments(text)
    assert masked.count("\n") == text.count("\n")
    assert "include" not in masked
    assert masked.startswith("a ")
    assert masked.rstrip().endswith("b")


def test_simple_graph(tmp_path: Path) -> None:
    main = write(tmp_path, "main.hlsl", '#include "common.hlsli"\n#include "lib/util.hlsli"\n')
    common = write(tmp_path, "common.hlsli", "float x;\n")
    util = write(tmp_path, "lib/util.hlsli", '#include "../common.hlsli"\nfloat y;\n')
    graph = build_include_graph(main)
    assert graph.ok
    assert set(graph.files) == {main.resolve(), common.resolve(), util.resolve()}
    assert graph.files[0] == main.resolve()


def test_includes_in_comments_are_ignored(tmp_path: Path) -> None:
    main = write(
        tmp_path, "main.hlsl", '// #include "missing.hlsli"\n/* #include "gone.hlsli" */\n'
    )
    assert build_include_graph(main).ok


def test_missing_include_has_location(tmp_path: Path) -> None:
    main = write(tmp_path, "main.hlsl", 'float a;\n\n#include "nope.hlsli"\n')
    graph = build_include_graph(main)
    assert not graph.ok
    (diag,) = graph.diagnostics
    assert diag.severity is Severity.ERROR
    assert diag.line == 3
    assert "nope.hlsli" in diag.message


def test_cycle_is_reported_once_without_looping(tmp_path: Path) -> None:
    a = write(tmp_path, "a.hlsl", '#include "b.hlsli"\n')
    write(tmp_path, "b.hlsli", '#include "c.hlsli"\n')
    write(tmp_path, "c.hlsli", '#include "b.hlsli"\n')
    graph = build_include_graph(a)
    cycles = [d for d in graph.diagnostics if "cycle" in d.message]
    assert len(cycles) == 1


def test_angle_includes_use_search_dirs_only(tmp_path: Path) -> None:
    main = write(tmp_path, "src/main.hlsl", "#include <lib.hlsli>\n")
    write(tmp_path, "src/lib.hlsli", "float local;\n")  # next to the includer: not found for <>
    missing = build_include_graph(main)
    assert not missing.ok
    shared = write(tmp_path, "shared/lib.hlsli", "float shared;\n")
    found = build_include_graph(main, [tmp_path / "shared"])
    assert found.ok
    assert shared.resolve() in found.files


def test_include_escaping_allowed_roots_is_refused(tmp_path: Path) -> None:
    secret = write(tmp_path, "private/secret.txt", "TOP SECRET\n")
    main = write(tmp_path, "project/main.hlsl", '#include "../private/secret.txt"\n')
    graph = build_include_graph(main)
    assert not graph.ok
    assert "outside the allowed directories" in graph.diagnostics[0].message
    assert secret.resolve() not in graph.files


def test_allowed_roots_can_be_widened(tmp_path: Path) -> None:
    shared = write(tmp_path, "shared/common.hlsli", "float x;\n")
    main = write(tmp_path, "project/main.hlsl", '#include "../shared/common.hlsli"\n')
    graph = build_include_graph(main, allowed_roots=[tmp_path])
    assert graph.ok
    assert shared.resolve() in graph.files


def test_flatten_expands_each_file_once(tmp_path: Path) -> None:
    write(tmp_path, "common.hlsli", "float shared_value;\n")
    write(tmp_path, "other.hlsli", '#include "common.hlsli"\nfloat other_value;\n')
    main = write(
        tmp_path, "main.hlsl", '#include "common.hlsli"\n#include "other.hlsli"\nvoid f() {}\n'
    )
    text = flatten(build_include_graph(main))
    assert text.count("float shared_value;") == 1
    assert "already included" in text
    assert "begin main.hlsl" in text
    assert text.index("shared_value") < text.index("other_value") < text.index("void f()")


def test_binary_include_is_not_followed_blindly(tmp_path: Path) -> None:
    blob = tmp_path / "blob.hlsli"
    blob.write_bytes(b"\x00\x01\x02")
    main = write(tmp_path, "main.hlsl", '#include "blob.hlsli"\n')
    with pytest.raises(InvalidInputError, match="binary"):
        build_include_graph(main)
