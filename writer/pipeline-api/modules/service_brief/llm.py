"""Model-tiered Claude helper for the Service Page Brief Generator.

The PRD calls for model tiering (§7): a cheap tier for per-page competitor
teardown extraction and a strong tier for the synthesis step. The blog brief's
`modules/brief/llm.py` hardcodes Sonnet, so this module adds a thin
model-parameterized wrapper. It REUSES the brief module's Anthropic client,
the global concurrency semaphore (one Anthropic account → one shared limiter),
and the tolerant JSON extractor rather than duplicating them.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from config import settings
from modules.brief.llm import (
    _STRICT_JSON_SUFFIX,
    _create_message,
    _extract_json_payload,
    get_anthropic,
)

from .cost import record_usage

logger = logging.getLogger(__name__)


async def claude_json_model(
    system: str,
    user: str,
    *,
    model: str,
    max_tokens: int = 2000,
    temperature: float = 0.2,
    expect_obj: bool = False,
) -> Any:
    """Call Claude on a caller-chosen model and parse the response as JSON.

    Mirrors `modules.brief.llm.claude_json` (tolerant parsing + one strict
    retry) but takes an explicit `model` so callers can pick the Haiku
    extraction tier vs the Sonnet synthesis tier. Shares the brief module's
    rate-limit semaphore.

    When `expect_obj=True`, the caller requires a JSON *object* (a dict). A
    response that parses to a valid-but-wrong-shape value (most often a
    top-level array, or prose whose first bracketed token is a stray list the
    tolerant extractor decodes) is treated as a retryable failure — the same
    strict-JSON retry that recovers a parse error also recovers a shape error,
    rather than the caller hard-failing the whole run on a single unlucky
    generation. A single-element `[obj]` wrapper (a common model mistake) is
    unwrapped instead of retried.
    """
    client = get_anthropic()

    last_error: Optional[Exception] = None
    for attempt in range(2):
        sys_prompt = system if attempt == 0 else system + _STRICT_JSON_SUFFIX
        # Route through the brief module's shared transport: semaphore-guarded,
        # transient-retried, AND failed over to the secondary Anthropic account
        # on a saturated primary (same model).
        message = await _create_message(client, {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": sys_prompt,
            "messages": [{"role": "user", "content": user}],
        })
        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        usage = getattr(message, "usage", None)
        if usage is not None:
            record_usage(
                model,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
            )
        if getattr(message, "stop_reason", None) == "max_tokens":
            logger.warning(
                "service_brief.llm.truncated",
                extra={"model": model, "max_tokens": max_tokens, "tail": text[-200:]},
            )
        try:
            payload = _extract_json_payload(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning(
                "service_brief.llm.parse_failed (attempt %s/2): %s head=%r",
                attempt + 1,
                exc,
                text[:300],
            )
            continue

        if expect_obj and not isinstance(payload, dict):
            # A single-object array is a benign wrapping mistake — unwrap it
            # rather than spend a retry.
            if (
                isinstance(payload, list)
                and len(payload) == 1
                and isinstance(payload[0], dict)
            ):
                return payload[0]
            last_error = ValueError(
                f"expected a JSON object, got {type(payload).__name__}"
            )
            logger.warning(
                "service_brief.llm.non_object (attempt %s/2): type=%s head=%r",
                attempt + 1,
                type(payload).__name__,
                text[:300],
            )
            continue

        return payload

    assert last_error is not None
    raise last_error


def extraction_model() -> str:
    """Cheap tier for per-page competitor teardown extraction (PRD §7)."""
    return settings.service_brief_extraction_model


def synthesis_model() -> str:
    """Strong tier reserved for the synthesis/reconciliation step (PRD §5/§7)."""
    return settings.service_brief_synthesis_model
