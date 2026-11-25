"""The script that picks which DXC release the CI downloads (shape of the GitHub releases API)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_select_dxc.py"
spec = importlib.util.spec_from_file_location("ci_select_dxc", SCRIPT)
assert spec is not None
assert spec.loader is not None
ci = importlib.util.module_from_spec(spec)
sys.modules["ci_select_dxc"] = ci
spec.loader.exec_module(ci)

LINUX = "linux_dxc_2026_01_01.x86_64.tar.gz"


def release(tag: str, published: str, *assets: str, draft: bool = False, pre: bool = False) -> dict:
    return {
        "tag_name": tag,
        "published_at": published,
        "draft": draft,
        "prerelease": pre,
        "assets": [{"name": name} for name in assets],
    }


RELEASES = [
    release("v1.9.2609.5", "2026-09-30", LINUX, "dxc_2026_09_30.zip"),
    release("v1.9.2608", "2026-08-10", LINUX),
    release("v1.8.2505.1", "2025-06-01", "linux_dxc_2025_06_01.x86_64.tar.gz"),
    release("v1.8.2403", "2024-04-01", "linux_dxc_2024_04_01.x86_64.tar.gz"),
]


def test_latest_is_the_newest_release_with_a_linux_build() -> None:
    assert ci.pick(RELEASES, "latest") == ("v1.9.2609.5", LINUX)


def test_older_is_the_newest_release_of_an_older_minor_series() -> None:
    tag, _asset = ci.pick(RELEASES, "older")
    assert tag == "v1.8.2505.1", "must skip v1.9.2608: it is the same series as the latest"


def test_the_order_comes_from_the_publication_date_not_the_list_order() -> None:
    assert ci.pick(list(reversed(RELEASES)), "latest")[0] == "v1.9.2609.5"
    assert ci.pick(list(reversed(RELEASES)), "older")[0] == "v1.8.2505.1"


def test_drafts_prereleases_and_releases_without_a_linux_build_are_skipped() -> None:
    releases = [
        release("v2.0.0-rc1", "2026-12-01", LINUX, pre=True),
        release("v1.9.9999", "2026-11-01", LINUX, draft=True),
        release("v1.9.2700", "2026-10-15", "dxc_2026_10_15.zip"),  # Windows archive only
        *RELEASES,
    ]
    assert ci.pick(releases, "latest")[0] == "v1.9.2609.5"


def test_the_windows_archive_is_never_chosen_as_the_linux_asset() -> None:
    (only,) = [release("v1.9.1", "2026-01-01", "dxc_2026_01_01.zip", LINUX)]
    assert ci.pick([only], "latest") == ("v1.9.1", LINUX)


def test_no_release_with_a_linux_build_is_an_error() -> None:
    with pytest.raises(ci.NoRelease):
        ci.pick([release("v1.9.1", "2026-01-01", "dxc.zip")], "latest")


def test_older_needs_an_older_series_to_exist() -> None:
    same_series = [RELEASES[0], RELEASES[1]]
    with pytest.raises(ci.NoRelease, match="older"):
        ci.pick(same_series, "older")


def test_an_unknown_selector_is_rejected() -> None:
    with pytest.raises(ValueError, match="latest"):
        ci.pick(RELEASES, "newest")


def test_the_command_line_prints_github_output_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(RELEASES)))
    assert ci.main(["ci_select_dxc.py", "older"]) == 0
    out = capsys.readouterr()
    assert out.out.splitlines() == ["tag=v1.8.2505.1", "asset=linux_dxc_2025_06_01.x86_64.tar.gz"]
    assert "selected DXC v1.8.2505.1" in out.err  # the human-readable line goes to stderr


def test_the_command_line_fails_cleanly_on_bad_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert ci.main(["ci_select_dxc.py", "latest"]) == 1
    assert "error:" in capsys.readouterr().err
    assert ci.main(["ci_select_dxc.py"]) == 2
