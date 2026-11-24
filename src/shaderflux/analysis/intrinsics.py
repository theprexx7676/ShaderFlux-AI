"""Intrinsic mapping data and the lint rules built on it."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from shaderflux.analysis.findings import Confidence, Finding
from shaderflux.core.models import Severity, ShaderLanguage
from shaderflux.pipeline.includes import mask_comments


@dataclass(frozen=True)
class Intrinsic:
    hlsl: str | None
    glsl: str | None
    note: str | None
    fix: str | None
    flag: bool
    rule: str | None
    title: str | None
    evidence: str


@lru_cache(maxsize=1)
def load_intrinsics() -> tuple[Intrinsic, ...]:
    """Load the bundled mapping table."""
    data = tomllib.loads(
        resources.files("shaderflux.analysis").joinpath("data/intrinsics.toml").read_text("utf-8")
    )
    return tuple(
        Intrinsic(
            hlsl=raw.get("hlsl"),
            glsl=raw.get("glsl"),
            note=raw.get("note"),
            fix=raw.get("fix"),
            flag=bool(raw.get("flag", False)),
            rule=raw.get("rule"),
            title=raw.get("title"),
            evidence=raw.get("evidence", "unverified"),
        )
        for raw in data["intrinsic"]
    )


def lookup(name: str) -> list[Intrinsic]:
    """Find mapping entries mentioning ``name`` in either language."""
    return [i for i in load_intrinsics() if name in (i.hlsl, i.glsl)]


_CONFIDENCE = {"verified": Confidence.HIGH, "documented": Confidence.MEDIUM}


def check_intrinsics(
    text: str, language: ShaderLanguage, *, file: str | None = None
) -> list[Finding]:
    """Report calls to intrinsics known to behave differently across languages."""
    if language not in (ShaderLanguage.HLSL, ShaderLanguage.GLSL):
        return []
    masked = mask_comments(text)
    findings: list[Finding] = []
    for entry in load_intrinsics():
        if not entry.flag:
            continue
        name = entry.hlsl if language is ShaderLanguage.HLSL else entry.glsl
        if not name or not re.fullmatch(r"\w+", name):
            continue
        for match in re.finditer(rf"\b{name}\s*\(", masked):
            findings.append(
                Finding(
                    rule=entry.rule or "INT000",
                    severity=Severity.NOTE,
                    message=f"{name}(): {entry.title}. {entry.note or ''}".strip(),
                    file=file,
                    line=masked.count("\n", 0, match.start()) + 1,
                    confidence=_CONFIDENCE.get(entry.evidence, Confidence.LOW),
                    suggestion=entry.fix,
                )
            )
    return findings
