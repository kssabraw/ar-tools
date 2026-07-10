"""Provider-selectable forced-tool-use LLM call for the narrative report
generators (maps_report, rank_analysis_report).

Both reports ask an LLM to emit a finished report via a single forced tool call
(`emit_report`). They historically ran on Anthropic Sonnet, but a per-keyword
scan fans out many concurrent calls that collide with everything else in the
suite on one Anthropic account's rate limit (429) — and the reports already
retry with backoff, so a saturated account blocks them outright. This helper
lets a report run on OpenAI instead (function-calling, the same pattern the
brand classifier uses), selected per-report via config, so the switch is a
one-line env change and fully reversible.

Pure transport only: one call, parse the tool result, return its arguments dict
(or None when the model didn't call the tool). Retry / empty-output validation
stays in the caller so each report keeps its own error semantics + tests.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


def is_transient_llm_error(exc: Exception) -> bool:
    """True for retryable provider failures on EITHER provider: rate limit (429),
    transient 5xx (overloaded), and connection drops. Lazy-imports each SDK so
    the pure helpers stay import-free and a missing SDK never breaks the check."""
    for mod_name in ("anthropic", "openai"):
        try:
            mod = __import__(mod_name)
        except Exception:  # noqa: BLE001 — SDK not installed / import error
            continue
        rate_limit = getattr(mod, "RateLimitError", None)
        conn_err = getattr(mod, "APIConnectionError", None)
        status_err = getattr(mod, "APIStatusError", None)
        if rate_limit and isinstance(exc, rate_limit):
            return True
        if conn_err and isinstance(exc, conn_err):
            return True
        if status_err and isinstance(exc, status_err):
            code = getattr(exc, "status_code", None) or 0
            if code == 429 or code >= 500:
                return True
    return False


async def _run_anthropic(
    *, model: str, system: str, user: str, tool_name: str,
    tool_description: str, input_schema: dict, max_tokens: int,
) -> tuple[Optional[dict], object]:
    import anthropic  # lazy

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        tools=[{"name": tool_name, "description": tool_description, "input_schema": input_schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user}],
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return (block.input or {}), response.stop_reason
    return None, response.stop_reason


async def _run_openai(
    *, model: str, system: str, user: str, tool_name: str,
    tool_description: str, input_schema: dict, max_tokens: int,
) -> tuple[Optional[dict], object]:
    import openai  # lazy

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[{
            "type": "function",
            "function": {"name": tool_name, "description": tool_description, "parameters": input_schema},
        }],
        tool_choice={"type": "function", "function": {"name": tool_name}},
    )
    choice = response.choices[0]
    calls = choice.message.tool_calls or []
    if not calls or calls[0].function.name != tool_name:
        return None, choice.finish_reason
    try:
        return json.loads(calls[0].function.arguments), choice.finish_reason
    except (ValueError, TypeError):
        return None, choice.finish_reason


async def run_forced_tool(
    *,
    provider: str,
    model: str,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    max_tokens: int,
) -> dict:
    """One forced tool call on the selected provider; returns the tool arguments.
    Raises RuntimeError('report_no_tool_use ...') when the model didn't emit the
    tool (the caller decides whether that's retryable)."""
    runner = _run_openai if provider == "openai" else _run_anthropic
    out, stop = await runner(
        model=model, system=system, user=user, tool_name=tool_name,
        tool_description=tool_description, input_schema=input_schema, max_tokens=max_tokens,
    )
    if out is None:
        raise RuntimeError(f"report_no_tool_use (provider={provider} stop={stop})")
    return out
