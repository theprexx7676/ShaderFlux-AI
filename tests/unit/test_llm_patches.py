"""Tests for safe patch application."""

from __future__ import annotations

import pytest

from shaderflux.llm.patches import PatchError, apply_patch
from shaderflux.llm.schemas import Edit, PatchProposal

pytestmark = pytest.mark.unit

SOURCE = "line one\nline two\nline three\nline four\n"


def proposal(*edits: Edit) -> PatchProposal:
    return PatchProposal(summary="s", edits=list(edits), confidence="high")


def edit(start: int, end: int, expected: str, replacement: str, file: str = "a.frag") -> Edit:
    return Edit(
        file=file,
        start_line=start,
        end_line=end,
        expected=expected,
        replacement=replacement,
        reason="r",
    )


def test_single_line_replacement_and_diff() -> None:
    result = apply_patch({"a.frag": SOURCE}, proposal(edit(2, 2, "line two", "LINE 2")))
    assert result.files["a.frag"] == "line one\nLINE 2\nline three\nline four\n"
    assert "-line two" in result.diff
    assert "+LINE 2" in result.diff
    assert result.changed_lines == 1


def test_original_input_is_not_modified() -> None:
    files = {"a.frag": SOURCE}
    apply_patch(files, proposal(edit(1, 1, "line one", "x")))
    assert files["a.frag"] == SOURCE


def test_multiple_edits_apply_regardless_of_order() -> None:
    result = apply_patch(
        {"a.frag": SOURCE},
        proposal(edit(4, 4, "line four", "FOUR"), edit(1, 2, "line one\nline two", "ONE-TWO")),
    )
    assert result.files["a.frag"] == "ONE-TWO\nline three\nFOUR\n"


def test_multi_line_replacement_and_deletion() -> None:
    grown = apply_patch({"a.frag": SOURCE}, proposal(edit(2, 2, "line two", "a\nb\nc")))
    assert grown.files["a.frag"].splitlines() == [
        "line one",
        "a",
        "b",
        "c",
        "line three",
        "line four",
    ]
    deleted = apply_patch({"a.frag": SOURCE}, proposal(edit(2, 3, "line two\nline three", "")))
    assert deleted.files["a.frag"] == "line one\nline four\n"


def test_crlf_and_trailing_newline_are_preserved() -> None:
    crlf = "one\r\ntwo\r\nthree\r\n"
    result = apply_patch({"a.frag": crlf}, proposal(edit(2, 2, "two", "TWO")))
    assert result.files["a.frag"] == "one\r\nTWO\r\nthree\r\n"
    no_trailing = apply_patch({"a.frag": "one\ntwo"}, proposal(edit(2, 2, "two", "TWO")))
    assert no_trailing.files["a.frag"] == "one\nTWO"


def test_stale_edit_is_rejected() -> None:
    with pytest.raises(PatchError, match="do not match"):
        apply_patch({"a.frag": SOURCE}, proposal(edit(2, 2, "line TWO", "x")))


def test_expected_tolerates_surrounding_newlines_and_cr() -> None:
    apply_patch({"a.frag": "one\r\ntwo\r\n"}, proposal(edit(1, 2, "one\ntwo\n", "x")))


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [(3, 2, "before start_line"), (4, 9, "past the end"), (9, 9, "past the end")],
)
def test_bad_ranges_are_rejected(start: int, end: int, message: str) -> None:
    with pytest.raises(PatchError, match=message):
        apply_patch({"a.frag": SOURCE}, proposal(edit(start, end, "line four", "x")))


def test_overlapping_edits_are_rejected() -> None:
    with pytest.raises(PatchError, match="overlap"):
        apply_patch(
            {"a.frag": SOURCE},
            proposal(
                edit(1, 2, "line one\nline two", "x"), edit(2, 3, "line two\nline three", "y")
            ),
        )


def test_unknown_and_read_only_files_are_rejected() -> None:
    files = {"a.frag": SOURCE, "common.glsl": "x\n"}
    with pytest.raises(PatchError, match="not provided"):
        apply_patch(files, proposal(edit(1, 1, "x", "y", file="/etc/passwd")))
    with pytest.raises(PatchError, match="read-only"):
        apply_patch(
            files,
            proposal(edit(1, 1, "x", "y", file="common.glsl")),
            editable=frozenset({"a.frag"}),
        )


def test_empty_proposal_is_rejected() -> None:
    with pytest.raises(PatchError, match="no edits"):
        apply_patch({"a.frag": SOURCE}, proposal())


def test_large_rewrites_need_permission() -> None:
    big = "\n".join(f"line {i}" for i in range(100)) + "\n"
    expected = "\n".join(f"line {i}" for i in range(100))
    replacement = "\n".join(f"new {i}" for i in range(100))
    with pytest.raises(PatchError, match="--allow-large-edits"):
        apply_patch({"a.frag": big}, proposal(edit(1, 100, expected, replacement)))
    allowed = apply_patch(
        {"a.frag": big}, proposal(edit(1, 100, expected, replacement)), allow_large=True
    )
    assert allowed.changed_lines == 100


def test_failure_changes_nothing_even_with_several_files() -> None:
    files = {"a.frag": SOURCE, "b.frag": SOURCE}
    with pytest.raises(PatchError):
        apply_patch(
            files,
            proposal(
                edit(1, 1, "line one", "ok", file="a.frag"),
                edit(1, 1, "WRONG", "no", file="b.frag"),
            ),
        )
    assert files == {"a.frag": SOURCE, "b.frag": SOURCE}
