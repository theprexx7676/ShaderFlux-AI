"""Structured shapes the model must answer with, and their JSON schemas."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from shaderflux.core.errors import LlmError


class Edit(BaseModel):
    """Replace lines ``start_line..end_line`` (1-based, inclusive) of ``file``."""

    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    expected: str  # the original text of those lines; a mismatch means the edit is stale
    replacement: str
    reason: str


class PatchProposal(BaseModel):
    summary: str
    edits: list[Edit]
    confidence: Literal["low", "medium", "high"]


# Written by hand (no $ref / $defs) because structured-output schemas are restricted.
PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "expected": {"type": "string"},
                    "replacement": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "file",
                    "start_line",
                    "end_line",
                    "expected",
                    "replacement",
                    "reason",
                ],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["summary", "edits", "confidence"],
    "additionalProperties": False,
}


def parse_proposal(text: str) -> PatchProposal:
    """Validate the model's JSON. Anything malformed is an :class:`LlmError`."""
    try:
        return PatchProposal.model_validate(json.loads(text))
    except json.JSONDecodeError as exc:
        raise LlmError(f"the model's answer was not valid JSON: {exc.msg}") from exc
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise LlmError(
            f"the model's answer did not match the schema at {where}: {first['msg']}"
        ) from exc
