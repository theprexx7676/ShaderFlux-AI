"""The LLM provider interface and a scripted fake for tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from shaderflux.core.errors import LlmError

# Opus is the default per the Claude API guidance; change it in `[llm] model` or
# SHADERFLUX_MODEL. Nothing in the code depends on this particular model.
DEFAULT_MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class LlmRequest:
    """Everything sent to the model, kept as plain data so it can be shown (--dry-run)."""

    task: str
    system: str
    user: str
    schema: dict[str, Any]
    max_tokens: int = 16000
    effort: str = "high"
    prompt_version: str = ""

    def describe(self) -> str:
        """Human-readable copy of exactly what would be sent."""
        return (
            f"task: {self.task} (prompt version {self.prompt_version})\n"
            f"effort: {self.effort}, max_tokens: {self.max_tokens}\n"
            f"--- system ---\n{self.system}\n--- user ---\n{self.user}\n"
        )


@dataclass(frozen=True)
class LlmResponse:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    stop_reason: str | None = None
    request_id: str | None = None


@dataclass
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, response: LlmResponse) -> None:
        self.input_tokens += response.input_tokens
        self.output_tokens += response.output_tokens
        self.calls += 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class LlmProvider(Protocol):
    name: str

    def complete(self, request: LlmRequest) -> LlmResponse: ...


@dataclass
class FakeProvider:
    """Replays scripted responses, so the whole repair loop runs offline in CI.

    Each item is a JSON string, an :class:`LlmResponse`, or an exception to raise.
    """

    script: Sequence[str | LlmResponse | Exception]
    name: str = "fake"
    requests: list[LlmRequest] = field(default_factory=list)

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self.script):
            raise LlmError("the fake provider has no more scripted responses")
        item = self.script[index]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LlmResponse):
            return item
        return LlmResponse(text=item, model="fake", input_tokens=100, output_tokens=50)
