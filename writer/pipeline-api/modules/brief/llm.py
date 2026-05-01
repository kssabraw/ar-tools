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

async def claude_json(
    system: str,
    user: str,
    max_tokens: int = 1500,
    temperature: float = 0.2,
) -> Any:
    """Call Claude and parse the response as JSON.

    Strips ```json fences if present. Raises ValueError if no JSON found.
    """
    client = get_anthropic()
    message = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(
        block.text for block in message.content if getattr(block, "type", "") == "text"
    ).strip()

    # Strip markdown fences
    fence = re.match(r"^```(?:json)?\s*\n(.*?)\n```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # Or grab the first JSON object/array
    if not text.startswith(("[", "{")):
        match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if match:
            text = match.group(1)

    return json.loads(text)


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
