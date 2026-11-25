"""Typed error hierarchy.

Every failure that the tool can anticipate maps to one of these classes so the
CLI can print an actionable message instead of a traceback.
"""

from __future__ import annotations


class ShaderFluxError(Exception):
    """Base class for all expected errors."""


class InvalidInputError(ShaderFluxError):
    """The user supplied something we cannot work with (bad path, bad option, ...)."""


class ToolMissingError(ShaderFluxError):
    """An external tool could not be found."""

    def __init__(self, tool: str, hint: str | None = None) -> None:
        self.tool = tool
        self.hint = hint
        message = f"required tool not found: {tool}"
        if hint:
            message += f" ({hint})"
        super().__init__(message)


class ToolFailedError(ShaderFluxError):
    """An external tool ran but did not finish normally (timeout, crash, ...)."""

    def __init__(self, tool: str, reason: str) -> None:
        self.tool = tool
        self.reason = reason
        super().__init__(f"{tool} failed: {reason}")


class ToolTimeoutError(ToolFailedError):
    """An external tool exceeded its time limit and was killed."""

    def __init__(self, tool: str, timeout: float) -> None:
        self.timeout = timeout
        super().__init__(tool, f"timed out after {timeout:g}s")


class UnsupportedRouteError(ShaderFluxError):
    """No conversion route exists between the requested languages."""


class LlmError(ShaderFluxError):
    """The LLM provider failed or returned something unusable."""


class VerificationFailedError(ShaderFluxError):
    """A verification step failed."""
