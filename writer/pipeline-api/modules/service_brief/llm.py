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
    _extract_json_payload,
    _get_anthropic_semaphore,
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
) -> Any:
    """Call Claude on a caller-chosen model and parse the response as JSON.

    Mirrors `modules.brief.llm.claude_json` (tolerant parsing + one strict
    retry) but takes an explicit `model` so callers can pick the Haiku
    extraction tier vs the Sonnet synthesis tier. Shares the brief module's
    rate-limit semaphore.
    """
    client = get_anthropic()
    semaphore = _get_anthropic_semaphore()

    last_error: Optional[Exception] = None
    for attempt in range(2):
        sys_prompt = system if attempt == 0 else system + _STRICT_JSON_SUFFIX
        async with semaphore:
            message = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=sys_prompt,
                messages=[{"role": "user", "content": user}],
            )
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
            return _extract_json_payload(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning(
                "service_brief.llm.parse_failed (attempt %s/2): %s head=%r",
                attempt + 1,
                exc,
                text[:300],
            )
            continue

    assert last_error is not None
    raise last_error


def extraction_model() -> str:
    """Cheap tier for per-page competitor teardown extraction (PRD §7)."""
    return settings.service_brief_extraction_model


def synthesis_model() -> str:
    """Strong tier reserved for the synthesis/reconciliation step (PRD §5/§7)."""
    return settings.service_brief_synthesis_model
