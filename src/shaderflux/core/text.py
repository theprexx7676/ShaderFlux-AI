"""Small text helpers shared by the analysis code."""

from __future__ import annotations

from bisect import bisect_right
from itertools import accumulate


class LineIndex:
    """Turn a character offset into a 1-based line number in O(log n).

    Counting newlines from the start for every match is O(n) each, which made big
    files quadratic. Build the index once per text instead.
    """

    def __init__(self, text: str) -> None:
        # offset of the first character of every line after the first
        self._starts = list(accumulate(len(part) + 1 for part in text.split("\n")))[:-1]

    def line_of(self, offset: int) -> int:
        return bisect_right(self._starts, offset) + 1
