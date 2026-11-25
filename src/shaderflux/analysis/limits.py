"""Hard limits for the lint rules.

The rules scan untrusted text with regular expressions. They are written to run in
linear time, but a limit is a second line of defence: a shader that is absurdly
large, or has absurdly long lines, is reported and skipped instead of risking a hang
in someone's CI job.
"""

from __future__ import annotations

from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.core.models import Severity

MAX_LINT_CHARS = 2_000_000
MAX_LINE_CHARS = 20_000


def exceeds_limits(text: str) -> str | None:
    """Return a human-readable reason if ``text`` is too big to analyse, else ``None``."""
    if len(text) > MAX_LINT_CHARS:
        return f"it has {len(text):,} characters (limit {MAX_LINT_CHARS:,})"
    longest = max((len(line) for line in text.split("\n")), default=0)
    if longest > MAX_LINE_CHARS:
        return f"it has a line of {longest:,} characters (limit {MAX_LINE_CHARS:,})"
    return None


def skipped_finding(reason: str, file: str | None) -> Finding:
    return Finding(
        rule="LNT001",
        severity=Severity.WARNING,
        message=f"not analysed: {reason}",
        file=file,
        line=1,
        confidence=Confidence.HIGH,
        suggestion="split the file, or lint the hand-written source instead of generated output",
    )
