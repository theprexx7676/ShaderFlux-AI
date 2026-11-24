"""Tests for atomic output writing and the translation cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from shaderflux.core.errors import InvalidInputError
from shaderflux.core.models import TranslationResult
from shaderflux.pipeline.cache import TranslationCache, make_key
from shaderflux.pipeline.output import write_output

pytestmark = pytest.mark.unit


def text_result(text: str = "void main() {}") -> TranslationResult:
    return TranslationResult(ok=True, output_text=text)


def test_write_text_and_bytes(tmp_path: Path) -> None:
    out = write_output(text_result("hello"), tmp_path / "sub" / "a.glsl")
    assert out.read_text() == "hello"
    binary = TranslationResult(ok=True, output_bytes=b"\x03\x02\x23\x07")
    assert write_output(binary, tmp_path / "m.spv").read_bytes() == b"\x03\x02\x23\x07"


def test_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "a.glsl"
    target.write_text("original")
    with pytest.raises(InvalidInputError, match="--force"):
        write_output(text_result("new"), target)
    assert target.read_text() == "original"
    write_output(text_result("new"), target, force=True)
    assert target.read_text() == "new"


def test_refuses_failed_or_empty_results(tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="failed"):
        write_output(TranslationResult(ok=False), tmp_path / "x")
    with pytest.raises(InvalidInputError, match="no output"):
        write_output(TranslationResult(ok=True), tmp_path / "x")


def test_no_temp_files_left_behind(tmp_path: Path) -> None:
    write_output(text_result(), tmp_path / "a.glsl")
    assert [p.name for p in tmp_path.iterdir()] == ["a.glsl"]


def test_cache_round_trip_text_and_bytes(tmp_path: Path) -> None:
    cache = TranslationCache(tmp_path / "cache")
    key = make_key(["a", "b"])
    assert cache.get(key) is None
    cache.put(key, TranslationResult(ok=True, output_text="x", output_bytes=b"\x01"))
    hit = cache.get(key)
    assert hit is not None
    assert hit.cached
    assert hit.output_text == "x"
    assert hit.output_bytes == b"\x01"


def test_cache_ignores_failures_and_corruption(tmp_path: Path) -> None:
    cache = TranslationCache(tmp_path)
    cache.put("k1", TranslationResult(ok=False))
    assert cache.get("k1") is None
    (tmp_path / "k2.json").write_text("{not json")
    assert cache.get("k2") is None
    (tmp_path / "k3.json").write_text('{"ok": true}')  # valid but has no output
    assert cache.get("k3") is None


def test_cache_write_failure_is_silent(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    TranslationCache(blocker / "sub").put("k", text_result())  # parent is a file: must not raise


def test_make_key_is_order_and_boundary_sensitive() -> None:
    assert make_key(["a", "b"]) != make_key(["b", "a"])
    assert make_key(["ab", "c"]) != make_key(["a", "bc"])
    assert make_key(["a"]) == make_key(["a"])
