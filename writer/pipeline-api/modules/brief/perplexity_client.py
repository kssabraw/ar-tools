"""Perplexity sonar-pro client for web-grounded research.

Used by `reddit_research.py` to query Reddit and synthesize a structured
insights document. Sonar-pro is purpose-built for "search the web (with
strong Reddit coverage), then synthesize" — collapsing what would
otherwise require separate fetch + parse + synthesis steps into one API
call.

API reference: https://docs.perplexity.ai/api-reference/chat-completions

Authentication: requires `PERPLEXITY_API_KEY` env var. Without it,
`perplexity_chat` raises `PerplexityUnavailable` so callers can fall
back gracefully without aborting the run.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

PERPLEXITY_BASE_URL = "https://api.perplexity.ai"
DEFAULT_MODEL = "sonar-pro"
DEFAULT_TIMEOUT_SECONDS = 60.0


class PerplexityUnavailable(Exception):
    """Raised when no API key is configured. Callers should fall back."""


class PerplexityError(Exception):
    """Raised on non-2xx HTTP responses or malformed payloads."""


async def perplexity_chat(
    *,
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    http_client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Single Perplexity sonar-pro call. Returns the parsed JSON response.

    The response structure mirrors OpenAI's chat-completions shape:
      {
        "choices": [{"message": {"content": "..."}}],
        "citations": ["url1", "url2", ...],
        ...
      }

    Callers should pull `choices[0].message.content` for the synthesized
    text and `citations` for the URL list.

    Raises:
        PerplexityUnavailable: when no API key is set.
        PerplexityError: on HTTP errors or malformed responses.
    """
    api_key = settings.perplexity_api_key
    if not api_key:
        raise PerplexityUnavailable(
            "PERPLEXITY_API_KEY not set; Reddit research falls back to raw context"
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await client.post(
            f"{PERPLEXITY_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )
        if response.status_code >= 400:
            body = response.text[:500]
            raise PerplexityError(
                f"perplexity HTTP {response.status_code}: {body}"
            )
        try:
            data = response.json()
        except Exception as exc:
            raise PerplexityError(f"perplexity returned non-JSON: {exc}")
        if not isinstance(data, dict) or "choices" not in data:
            raise PerplexityError(f"perplexity payload missing choices: {data!r}"[:300])
        return data
    finally:
        if owns_client:
            await client.aclose()


def extract_content_and_citations(payload: dict) -> tuple[str, list[str]]:
    """Pull (content, citations) from a Perplexity chat-completions response.

    Returns ("", []) on missing fields rather than raising — the caller's
    validation step will detect empty content / thin citations and route
    to the fallback path.
    """
    choices = payload.get("choices") or []
    content = ""
    if choices and isinstance(choices, list):
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message") or {}
            if isinstance(msg, dict):
                content = msg.get("content") or ""

    raw_citations = payload.get("citations") or []
    citations: list[str] = []
    if isinstance(raw_citations, list):
        for c in raw_citations:
            if isinstance(c, str) and c.strip():
                citations.append(c.strip())
            elif isinstance(c, dict):
                url = c.get("url") or c.get("href")
                if isinstance(url, str) and url.strip():
                    citations.append(url.strip())

    return content, citations
