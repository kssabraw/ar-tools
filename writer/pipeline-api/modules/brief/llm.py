"""LLM helpers used by the Brief Generator.

- Anthropic Claude Sonnet 4.6 for: heading polish, intent borderline check,
  authority gap agent, FAQ concern extraction, response content extraction,
  how-to reordering.
- OpenAI text-embedding-3-small for: semantic scoring (Step 5) and
  cluster grouping (Step 9, reuses same vectors).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from config import settings

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
EMBEDDING_MODEL = "text-embedding-3-small"

_anthropic: Optional[AsyncAnthropic] = None
_openai: Optional[AsyncOpenAI] = None


def get_anthropic() -> AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic


def get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai


# ---- Anthropic helpers ----

_STRICT_JSON_SUFFIX = (
    "\n\nIMPORTANT: Respond with ONLY a single JSON object. "
    "No prose preamble, no commentary, no markdown code fences."
)


def _extract_json_payload(text: str) -> Any:
    """Parse a JSON value out of a model response that may contain prose,
    markdown fences, or trailing commentary.

    Strategy:
    1. Try parsing the full string verbatim (fast path for clean responses).
    2. Strip a markdown code fence if one wraps the payload.
    3. Walk forward through the text; at every `[` or `{` try
       `json.JSONDecoder().raw_decode()` — that returns the first complete
       JSON value and ignores trailing prose.

    Raises json.JSONDecodeError if no parseable JSON value is found.
    """
    stripped = text.strip()
    if not stripped:
        raise json.JSONDecodeError("empty response", text, 0)

    # Fast path: clean JSON
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Strip a fenced block if one wraps the payload (relaxed — does not
    # require the fence to be at start/end of the entire string)
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
        candidate = fence.group(1).strip()
    else:
        candidate = stripped

    # Walk forward, looking for the first position from which a complete
    # JSON value can be decoded. raw_decode stops at the natural end of
    # the value and does not care about trailing prose.
    decoder = json.JSONDecoder()
    for i, ch in enumerate(candidate):
        if ch in "[{":
            try:
                obj, _ = decoder.raw_decode(candidate[i:])
                return obj
            except json.JSONDecodeError:
                continue

    raise json.JSONDecodeError(
        "no JSON object or array could be decoded from response",
        text,
        0,
    )


async def claude_json(
    system: str,
    user: str,
    max_tokens: int = 1500,
    temperature: float = 0.2,
) -> Any:
    """Call Claude and parse the response as JSON.

    Tolerates fenced/prose-wrapped responses. On parse failure, retries
    once with a stricter "JSON only" addendum to the system prompt and
    logs a snippet of the offending response for diagnosis.
    """
    client = get_anthropic()

    last_error: Optional[Exception] = None
    last_text: str = ""
    for attempt in range(2):
        sys_prompt = system if attempt == 0 else system + _STRICT_JSON_SUFFIX
        message = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            system=sys_prompt,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        last_text = text
        try:
            return _extract_json_payload(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning(
                "claude_json parse failed (attempt %s/2): %s — response head=%r",
                attempt + 1,
                exc,
                text[:500],
            )
            continue

    assert last_error is not None
    raise last_error


async def claude_text(
    system: str,
    user: str,
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> str:
    client = get_anthropic()
    message = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(
        block.text for block in message.content if getattr(block, "type", "") == "text"
    ).strip()


# ---- OpenAI embeddings ----

async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. Returns one vector per input."""
    if not texts:
        return []
    client = get_openai()
    # OpenAI accepts up to 2048 inputs per call; we won't approach that.
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
