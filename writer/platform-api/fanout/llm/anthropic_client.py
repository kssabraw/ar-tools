"""Anthropic wrapper for the article planning orchestrator (PRD §7.10, §14.2).

Claude Opus 4.7 in tool-use mode: the orchestrator is forced to emit its output
through a single tool whose `input_schema` is the §7.10.3 article-plan schema, so
the shape is enforced by the model rather than parsed out of prose. No browsing —
all evidence (SERPs, groupings, keyword pool) is in the prompt.

Every model call emits an `llm_call` structured log (PRD §16.3).
"""

import logging
import random
import time

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

from fanout.cancellation import raise_if_cancelled
from fanout.cost_meter import llm_token_cost, record_cost

logger = logging.getLogger(__name__)


class AnthropicError(Exception):
    pass


# Transport errors worth retrying in-process: a 429 rate-limit or 529 overload
# clears on its own, so backing off and re-issuing the call beats degrading the
# chunk to passthrough (the M5 gap that left e.g. a competitor article as a raw
# Louvain grouping). The SDK's own 2 default retries proved insufficient under
# the orchestrator's parallel fan-out, so we add an outer backoff — mirroring the
# M6 architect fix — and pair it with a lower worker count (config).
_RETRYABLE_EXC = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, _RETRYABLE_EXC):
        return True
    if isinstance(exc, APIStatusError):
        return getattr(exc, "status_code", None) in _RETRYABLE_STATUS
    return False


class AnthropicLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_tokens: int = 8000,
        timeout_s: float = 120.0,
        max_transport_attempts: int = 4,
    ):
        self._client = Anthropic(api_key=api_key, timeout=timeout_s)
        self._model = model
        self._max_tokens = max_tokens
        self._max_transport_attempts = max(1, max_transport_attempts)

    def _invoke(self, *, create_kwargs: dict, purpose: str):
        """Shared transport-retry + cost/logging wrapper around the Messages API.
        Returns the raw response; callers extract the tool_use / text block.

        STREAMING, not messages.create: the orchestrator's big chunk calls
        (large prompt, up to 16k output tokens) can generate for many minutes,
        and a non-streaming request sends no bytes until completion — idle
        upstream connections get killed at ~2 minutes regardless of the
        client-side timeout (observed in production as an APIConnectionError
        retry loop that starved article planning). Streaming keeps bytes
        flowing for the whole generation; get_final_message() returns the same
        Message object messages.create would have, so callers are unchanged."""
        raise_if_cancelled()
        started = time.perf_counter()
        resp = None
        for attempt in range(self._max_transport_attempts):
            try:
                with self._client.messages.stream(
                    model=self._model, **create_kwargs
                ) as stream:
                    resp = stream.get_final_message()
                break
            except Exception as exc:  # noqa: BLE001 — surfaced as AnthropicError
                # Retry only transient transport errors (rate-limit / overload /
                # timeout); anything else (auth, bad-request, …) fails fast.
                if _is_retryable(exc) and attempt < self._max_transport_attempts - 1:
                    # Exponential backoff with jitter (1.5s, 3s, 6s, capped at 8s).
                    time.sleep(min(8.0, 1.5 * (2 ** attempt)) + random.uniform(0, 0.5))
                    continue
                raise AnthropicError(f"Anthropic call failed ({purpose}): {exc}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        usage = getattr(resp, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        cost = llm_token_cost(self._model, input_tokens, output_tokens)
        record_cost(cost)  # PRD §16.4 — token-derived cost
        logger.info(
            "llm_call",
            extra={
                "event": "llm_call", "purpose": purpose, "provider": "anthropic",
                "model": self._model, "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens, "latency_ms": latency_ms,
                "cost_usd": cost, "status": "success",
            },
        )
        return resp

    def call_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict,
        purpose: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict:
        """Force a single tool call and return its `input` dict (the structured
        output). Raises AnthropicError on transport failure or a missing tool
        block; the caller owns reprompt/degrade policy (PRD §16.2). `max_tokens` /
        `temperature` override the instance defaults per the §17 call inventory."""
        create_kwargs: dict = {
            "max_tokens": max_tokens or self._max_tokens,
            "system": system,
            "tools": [{"name": tool_name, "description": tool_description,
                       "input_schema": input_schema}],
            "tool_choice": {"type": "tool", "name": tool_name},
            "messages": [{"role": "user", "content": user}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        resp = self._invoke(create_kwargs=create_kwargs, purpose=purpose)

        for block in resp.content or []:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                data = block.input
                if isinstance(data, dict):
                    return data
                raise AnthropicError(f"Tool input was not an object ({purpose})")
        raise AnthropicError(f"Model returned no tool_use block ({purpose})")

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Plain-text prose call (Writer §17 calls #5/#7 — section + conclusion). Returns
        the concatenated text blocks. Raises AnthropicError on transport failure."""
        create_kwargs: dict = {
            "max_tokens": max_tokens or self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        resp = self._invoke(create_kwargs=create_kwargs, purpose=purpose)
        return "".join(
            getattr(b, "text", "") for b in (resp.content or [])
            if getattr(b, "type", None) == "text"
        ).strip()
