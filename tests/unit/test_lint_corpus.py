"""Lint accuracy on the hand-written corpus.

The corpus and the rules were written by the same people, so a perfect score is
a regression guard, not independent evidence. Real-world false positives found
later should be added here as new cases.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from shaderflux.analysis.lint import lint_file

pytestmark = pytest.mark.unit


def load_cases(corpus: Path) -> list[dict[str, object]]:
    return tomllib.loads((corpus / "lint_manifest.toml").read_text())["case"]


def test_manifest_covers_every_corpus_file(corpus: Path) -> None:
    listed = {str(c["file"]) for c in load_cases(corpus)}
    on_disk = {p.name for p in (corpus / "lint").iterdir() if p.is_file()}
    assert listed == on_disk


def test_each_case_reports_exactly_the_expected_rules(corpus: Path) -> None:
    problems = []
    for case in load_cases(corpus):
        got = {f.rule for f in lint_file(corpus / "lint" / str(case["file"])).findings}
        want = set(case["rules"])  # type: ignore[call-overload]
        if got != want:
            problems.append(f"{case['file']}: got {sorted(got)}, expected {sorted(want)}")
    assert not problems, "\n".join(problems)


def test_clean_shaders_have_no_findings_at_all(corpus: Path) -> None:
    for case in load_cases(corpus):
        if not case["rules"]:
            assert lint_file(corpus / "lint" / str(case["file"])).findings == []
