"""OpenAI-backed writer LLM for the Fanout blog writer — the "Luna" path.

Fanout's blog writer (`fanout/writer/pipeline.py`) drives its prose steps through
an LLM object exposing exactly two methods — `complete_text` (plain prose) and
`call_tool` (one forced tool call → the structured `input` dict) — which
`AnthropicLLM` provides. This adapter implements the SAME interface against
OpenAI (chat-completions + function calling), so `build_writer_deps` can hand the
writer a Luna-backed `section_llm`/`short_llm` when a run selects the OpenAI
content-writer provider.

GPT-5 notes (mirrors the suite's other OpenAI call sites):
  * `max_completion_tokens`, not `max_tokens`.
  * temperature is NOT sent (GPT-5 models reject a non-default temperature) — the
    `temperature` kwarg is accepted for signature parity and ignored.
  * `call_tool` uses a single forced function tool; the arguments come back as a
    JSON string on `tool_calls[0].function.arguments`.

Transport retry + `llm_call` cost logging match `OpenAILLM`/`AnthropicLLM`.
"""

import json
import logging
import random
import time

from openai import OpenAI

from fanout.cancellation import raise_if_cancelled
from fanout.cost_meter import llm_token_cost, record_cost
from fanout.llm.openai_client import LLMError, _is_retryable

logger = logging.getLogger(__name__)

_MAX_TRANSPORT_ATTEMPTS = 4
_DEFAULT_MAX_TOKENS = 4096


class OpenAIWriterLLM:
    """Drop-in for `AnthropicLLM` in the Fanout writer's `section_llm`/`short_llm`
    slots, backed by OpenAI (Luna)."""

    def __init__(self, api_key: str, model: str, max_tokens: int = _DEFAULT_MAX_TOKENS):
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def _create(self, *, create_kwargs: dict, purpose: str):
        raise_if_cancelled()
        started = time.perf_counter()
        resp = None
        for attempt in range(_MAX_TRANSPORT_ATTEMPTS):
            raise_if_cancelled()
            try:
                resp = self._client.chat.completions.create(model=self._model, **create_kwargs)
                break
            except Exception as exc:  # noqa: BLE001 — surfaced as LLMError to caller
                if _is_retryable(exc) and attempt < _MAX_TRANSPORT_ATTEMPTS - 1:
                    time.sleep(min(8.0, 1.5 * (2 ** attempt)) + random.uniform(0, 0.5))
                    continue
                raise LLMError(f"OpenAI writer call failed ({purpose}): {exc}") from exc
        usage = getattr(resp, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        cost = llm_token_cost(self._model, input_tokens, output_tokens)
        record_cost(cost)
        logger.info(
            "llm_call",
            extra={
                "event": "llm_call", "purpose": purpose, "provider": "openai",
                "model": self._model, "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "cost_usd": cost, "status": "success",
            },
        )
        return resp

    def complete_text(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
        max_tokens: int | None = None,
        temperature: float | None = None,  # noqa: ARG002 — parity; GPT-5 rejects it
    ) -> str:
        resp = self._create(
            create_kwargs={
                "max_completion_tokens": max_tokens or self._max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            purpose=purpose,
        )
        choice = (resp.choices or [None])[0]
        text = ""
        if choice is not None and getattr(choice, "message", None) is not None:
            text = choice.message.content or ""
        return text.strip()

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
        temperature: float | None = None,  # noqa: ARG002 — parity; GPT-5 rejects it
    ) -> dict:
        """Force a single function tool call and return its arguments dict —
        mirrors `AnthropicLLM.call_tool`. Raises LLMError on a missing/invalid
        tool call so the caller owns reprompt/degrade policy."""
        resp = self._create(
            create_kwargs={
                "max_completion_tokens": max_tokens or self._max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": input_schema,
                    },
                }],
                "tool_choice": {"type": "function", "function": {"name": tool_name}},
            },
            purpose=purpose,
        )
        choice = (resp.choices or [None])[0]
        message = getattr(choice, "message", None) if choice else None
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            fn = getattr(call, "function", None)
            if fn is not None and getattr(fn, "name", None) == tool_name:
                try:
                    data = json.loads(fn.arguments or "{}")
                except (json.JSONDecodeError, TypeError) as exc:
                    raise LLMError(f"Tool arguments were not valid JSON ({purpose})") from exc
                if isinstance(data, dict):
                    return data
                raise LLMError(f"Tool input was not an object ({purpose})")
        raise LLMError(f"Model returned no tool call ({purpose})")
