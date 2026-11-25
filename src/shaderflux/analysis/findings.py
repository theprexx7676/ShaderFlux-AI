"""The common result type for lint rules."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from shaderflux.core.models import Severity


class Confidence(StrEnum):
    LOW = "low"  # heuristic; may be a false alarm
    MEDIUM = "medium"
    HIGH = "high"  # follows directly from the source


class Finding(BaseModel):
    """One porting risk found in a shader."""

    rule: str
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    confidence: Confidence = Confidence.MEDIUM
    suggestion: str | None = None

    def format(self) -> str:
        where = ""
        if self.file:
            where = self.file + (f":{self.line}" if self.line is not None else "") + ": "
        text = f"{where}{self.severity.value}: [{self.rule}] {self.message}"
        if self.suggestion:
            text += f"\n    fix: {self.suggestion}"
        return text
