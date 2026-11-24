"""Claude via the official Anthropic SDK.

Not exercised against the live API in the development environment (no key was
available). The request shape follows the SDK's own parameters, which tests check
with a fake client, and every API failure is mapped to :class:`LlmError`.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from shaderflux.core.errors import LlmError
from shaderflux.llm.provider import DEFAULT_MODEL, LlmRequest, LlmResponse

log = logging.getLogger("shaderflux")

_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_NO_CREDENTIALS = (
    "no Anthropic credentials found: set the ANTHROPIC_API_KEY environment variable "
    "(or run `ant auth login`)"
)


class AnthropicProvider:
    """Send requests to Claude and return validated-by-the-caller JSON text.

    * The API key is never passed in code: the SDK reads ``ANTHROPIC_API_KEY`` (or
      an ``ant auth login`` profile) itself.
    * ``thinking`` and sampling parameters are deliberately **not** sent: the
      current models think by default and reject ``temperature`` / ``top_p``.
    * Structured output uses ``output_config.format`` (JSON schema); the caller
      still validates the result, because a schema cannot express every rule.
    * Server-side refusal fallbacks are tried first and dropped automatically if
      the API rejects them.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
        fallbacks: bool = True,
    ) -> None:
        self.model = model
        self._client = client
        self.fallbacks = fallbacks

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                self._client = anthropic.Anthropic()
            except anthropic.AnthropicError as exc:
                raise LlmError(_NO_CREDENTIALS) from exc
        return self._client

    # -- request ---------------------------------------------------------

    def build_kwargs(self, request: LlmRequest) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "output_config": {
                "effort": request.effort,
                "format": {"type": "json_schema", "schema": request.schema},
            },
        }

    def _create(self, client: Any, kwargs: dict[str, Any]) -> Any:
        if self.fallbacks:
            try:
                return client.beta.messages.create(
                    betas=[_FALLBACK_BETA], fallbacks="default", **kwargs
                )
            except anthropic.BadRequestError as exc:
                log.warning("refusal fallbacks were rejected (%s); retrying without them", exc)
        return client.messages.create(**kwargs)

    def complete(self, request: LlmRequest) -> LlmResponse:
        client = self._get_client()
        try:
            message = self._create(client, self.build_kwargs(request))
        except anthropic.AuthenticationError as exc:
            raise LlmError(
                "authentication failed: check ANTHROPIC_API_KEY (or run `ant auth login`)"
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LlmError(f"the API key lacks permission for this request: {exc.message}") from exc
        except anthropic.NotFoundError as exc:
            raise LlmError(
                f"model {self.model!r} was not found; set a valid one in [llm] model"
            ) from exc
        except anthropic.BadRequestError as exc:
            raise LlmError(f"the API rejected the request: {exc.message}") from exc
        except anthropic.RateLimitError as exc:
            retry = exc.response.headers.get("retry-after", "unknown")
            raise LlmError(f"rate limited by the API (retry after {retry}s)") from exc
        except anthropic.APIStatusError as exc:
            raise LlmError(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LlmError("could not reach the Anthropic API; check your network") from exc
        except TypeError as exc:
            # The SDK raises a bare TypeError at request time when no credentials exist.
            if "authentication method" in str(exc):
                raise LlmError(_NO_CREDENTIALS) from exc
            raise
        return self._to_response(message)

    # -- response --------------------------------------------------------

    @staticmethod
    def _to_response(message: Any) -> LlmResponse:
        stop = getattr(message, "stop_reason", None)
        if stop == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None)
            raise LlmError(
                "the model declined this request"
                + (f" (category: {category})" if category else "")
                + "; try again with a smaller or different shader"
            )
        if stop == "max_tokens":
            raise LlmError("the model's answer was cut off (max_tokens); try a smaller shader")
        text = next((b.text for b in message.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise LlmError("the model returned no text")
        usage = getattr(message, "usage", None)

        def count(name: str) -> int:
            return int(getattr(usage, name, 0) or 0)

        return LlmResponse(
            text=text,
            model=str(getattr(message, "model", "")),
            input_tokens=count("input_tokens"),
            output_tokens=count("output_tokens"),
            cache_read_tokens=count("cache_read_input_tokens"),
            cache_write_tokens=count("cache_creation_input_tokens"),
            stop_reason=stop,
            request_id=getattr(message, "_request_id", None),
        )
