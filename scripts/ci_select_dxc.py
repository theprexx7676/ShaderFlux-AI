#!/usr/bin/env python3
"""Pick the DXC release the CI job should download.

Reads the JSON list from ``GET /repos/microsoft/DirectXShaderCompiler/releases`` on standard
input and prints ``tag=...`` and ``asset=...`` lines (the format of ``$GITHUB_OUTPUT``).

* ``latest``: the newest published (not draft, not pre-release) release that has a Linux build.
* ``older``: the newest such release from an *older minor series by tag* than the latest one
  (for example v1.8.x when the latest is v1.9.x), so the second job tests a genuinely different
  build and not the previous patch of the same one. Note: Microsoft's v1.8.2505.1 Linux binary
  reports itself as ``1.9(dev;...)``, so the series is the release tag's, not what ``dxc --version``
  prints.

The Linux build is the asset named ``linux_dxc_*.tar.gz``. Used by ``.github/workflows/ci.yml``;
tested in ``tests/unit/test_ci_select_dxc.py``.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

LINUX_ASSET = re.compile(r"^linux_dxc_.*\.tar\.gz$")
SERIES = re.compile(r"^v?(\d+)\.(\d+)")


class NoRelease(Exception):
    """No release matches the request."""


def _series(tag: str) -> tuple[int, int] | None:
    match = SERIES.match(tag)
    return (int(match.group(1)), int(match.group(2))) if match else None


def usable_releases(releases: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """``(tag, linux asset name)`` of every usable release, newest first."""
    ordered = sorted(
        releases,
        key=lambda r: r.get("published_at") or r.get("created_at") or "",
        reverse=True,
    )
    found: list[tuple[str, str]] = []
    for release in ordered:
        if release.get("draft") or release.get("prerelease"):
            continue
        asset = next(
            (a["name"] for a in release.get("assets", []) if LINUX_ASSET.match(a.get("name", ""))),
            None,
        )
        if asset and release.get("tag_name"):
            found.append((release["tag_name"], asset))
    return found


def pick(releases: list[dict[str, Any]], which: str) -> tuple[str, str]:
    if which not in ("latest", "older"):
        raise ValueError(f"expected 'latest' or 'older', got {which!r}")
    usable = usable_releases(releases)
    if not usable:
        raise NoRelease("no published release has a Linux build (linux_dxc_*.tar.gz)")
    latest = usable[0]
    if which == "latest":
        return latest
    current = _series(latest[0])
    for tag, asset in usable[1:]:
        if _series(tag) != current:
            return tag, asset
    raise NoRelease(f"no older release series than {latest[0]} has a Linux build")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ci_select_dxc.py latest|older < releases.json", file=sys.stderr)
        return 2
    try:
        tag, asset = pick(json.load(sys.stdin), argv[1])
    except (NoRelease, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"selected DXC {tag} ({asset}) for '{argv[1]}'", file=sys.stderr)
    print(f"tag={tag}")
    print(f"asset={asset}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
