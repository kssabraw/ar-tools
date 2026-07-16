"""LLM helpers used by the Brief Generator.

- Anthropic Claude Sonnet 4.6 for: heading polish, intent borderline check,
  authority gap agent, FAQ concern extraction, response content extraction,
  how-to reordering, plus v2.0's title/scope generation, persona generation,
  and scope verification.
- Gemini embeddings for ALL vector work (suite standardized off OpenAI):
  `embed_batch` (legacy v1.8 brief, SIE filters, Research snippet ranking) and
  `embed_batch_large` (Brief v2.0 paraphrase discrimination + coverage graph)
  both delegate to `embed_gemini` in the SEMANTIC_SIMILARITY space; AIO
  proximity uses the asymmetric RETRIEVAL_QUERY/DOCUMENT spaces.

All Anthropic calls are wrapped in a single global semaphore (default 5
concurrent, configurable via `anthropic_max_concurrency`) to dodge the
per-account concurrent-connections rate limit. The brief pipeline fans
out Claude calls in a few places (silo viability checks, fan-out
subtopic extraction, parallel writer-side scoring) and unbounded
concurrency reliably trips HTTP 429 rate_limit_error. The semaphore is
acquired in `claude_json` and `claude_text` so every call site is
protected without requiring per-caller throttling.

On top of the semaphore, every call retries transient failures (429 rate
limit, 529 overloaded / 5xx, connection drops) with exponential backoff +
jitter (`anthropic_max_retries` / `anthropic_retry_base_seconds`) — the
semaphore can't help when the ACCOUNT is saturated by the suite's other
services sharing the key, and without retries a single 429 failed the
module and therefore the whole run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import secrets
from typing import Any, Optional

import anthropic
from anthropic import AsyncAnthropic
import httpx

from config import settings

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
# Opus for the single reasoning step (answer contract): it sets the whole
# brief's direction and must be willing to contradict a false premise. Opus 4.8
# rejects a `temperature` param, so callers pass temperature=None for it.
CLAUDE_OPUS_MODEL = "claude-opus-4-8"

_anthropic: Optional[AsyncAnthropic] = None

# Module-level semaphore guarding all `client.messages.create()` calls.
# Lazily constructed on first use so it binds to the running event loop
# rather than whatever loop existed at import time.
_anthropic_semaphore: Optional[asyncio.Semaphore] = None


def _get_anthropic_semaphore() -> asyncio.Semaphore:
    global _anthropic_semaphore
    if _anthropic_semaphore is None:
        _anthropic_semaphore = asyncio.Semaphore(
            settings.anthropic_max_concurrency
        )
    return _anthropic_semaphore


def get_anthropic() -> AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic


# ---- Anthropic helpers ----

_STRICT_JSON_SUFFIX = (
    "\n\nIMPORTANT: Respond with ONLY a single JSON object. "
    "No prose preamble, no commentary, no markdown code fences."
)


def _is_transient_anthropic_error(exc: Exception) -> bool:
    """Retryable Anthropic failures: 429 rate limit, 529 overloaded / 5xx,
    and connection drops. Auth/bad-request errors fail fast."""
    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


async def _create_message(client: AsyncAnthropic, create_kwargs: dict[str, Any]) -> Any:
    """One semaphore-guarded `messages.create` with transient-error retries.

    The semaphore prevents self-inflicted concurrency 429s; this loop covers
    account-wide saturation (the shared Anthropic key serves other suite
    services too). Backoff sleeps happen OUTSIDE the semaphore so a
    backing-off call never holds a concurrency slot, and jitter (0.5-1.5x)
    de-synchronizes parallel fan-out calls so they don't re-collide."""
    semaphore = _get_anthropic_semaphore()
    attempt = 0
    while True:
        try:
            async with semaphore:
                return await client.messages.create(**create_kwargs)
        except Exception as exc:  # noqa: BLE001 — classify, re-raise if terminal
            if attempt >= settings.anthropic_max_retries or not _is_transient_anthropic_error(exc):
                raise
            delay = settings.anthropic_retry_base_seconds * (2 ** attempt) * (
                0.5 + secrets.randbelow(1000) / 1000.0
            )
            logger.warning(
                "anthropic_transient_retry",
                extra={
                    "attempt": attempt + 1,
                    "delay_s": round(delay, 1),
                    "error": str(exc)[:200],
                },
            )
            await asyncio.sleep(delay)
            attempt += 1


def _extract_json_payload(text: str) -> Any:
    """Parse a JSON value out of a model response that may contain prose,
    markdown fences, or trailing commentary.

    Strategy:
    1. Try parsing the full string verbatim (fast path for clean responses).
    2. Strip a markdown code fence if one wraps the payload.
    3. Walk forward through the text; at every `[` or `{` try
       `json.JSONDecoder().raw_decode()` - that returns the first complete
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

    # Strip a fenced block if one wraps the payload (relaxed - does not
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
    temperature: Optional[float] = 0.2,
    model: Optional[str] = None,
) -> Any:
    """Call Claude and parse the response as JSON.

    Tolerates fenced/prose-wrapped responses. On parse failure, retries
    once with a stricter "JSON only" addendum to the system prompt and
    logs a snippet of the offending response for diagnosis.

    `model` defaults to CLAUDE_MODEL (Sonnet); pass CLAUDE_OPUS_MODEL for the
    answer-contract reasoning step. `temperature=None` omits the param entirely
    (Opus 4.8 rejects `temperature`).
    """
    client = get_anthropic()
    use_model = model or CLAUDE_MODEL

    last_error: Optional[Exception] = None
    for attempt in range(2):
        sys_prompt = system if attempt == 0 else system + _STRICT_JSON_SUFFIX
        create_kwargs: dict[str, Any] = {
            "model": use_model,
            "max_tokens": max_tokens,
            "system": sys_prompt,
            "messages": [{"role": "user", "content": user}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        message = await _create_message(client, create_kwargs)
        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )

        # Detect response truncation. When stop_reason == "max_tokens" the
        # JSON value is almost certainly incomplete (cut off mid-string),
        # which raw_decode cannot recover. Log loudly so operators can
        # bump the budget at the call site.
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "max_tokens":
            logger.warning(
                "claude_json.truncated",
                extra={
                    "attempt": attempt + 1,
                    "max_tokens": max_tokens,
                    "model": use_model,
                    "response_chars": len(text),
                    "tail": text[-200:],
                },
            )

        try:
            return _extract_json_payload(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning(
                "claude_json parse failed (attempt %s/2): %s - stop_reason=%s response head=%r",
                attempt + 1,
                exc,
                stop_reason,
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
    message = await _create_message(client, {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    })
    return "".join(
        block.text for block in message.content if getattr(block, "type", "") == "text"
    ).strip()


# ---- Text embeddings (Gemini) ----
#
# Brief v2, SIE, and Research embed through these two functions. They were
# OpenAI (`text-embedding-3-{small,large}`); the suite standardized on Gemini
# (AIO alignment + a single embedding space), so both now delegate to
# `embed_gemini` in the SEMANTIC_SIMILARITY space. Vectors are unit-normalized
# (cosine == dot) at `settings.gemini_embedding_dim`. Requires GEMINI_API_KEY —
# there is NO OpenAI fallback anymore.
_SIMILARITY_TASK = "SEMANTIC_SIMILARITY"


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts for symmetric similarity (Gemini). Used by the
    legacy brief pipeline, SIE, and Research. Returns one vector per input."""
    if not texts:
        return []
    return await embed_gemini(texts, task_type=_SIMILARITY_TASK)


async def embed_batch_large(
    texts: list[str],
    normalize: bool = True,
) -> list[list[float]]:
    """Embed a batch of texts for symmetric similarity (Gemini, Brief v2.0).

    Vectors are unit-normalized so cosine == dot product. `normalize` is kept
    for signature compatibility; the Gemini path always L2-normalizes (its
    truncated <3072-dim outputs require it), so it is effectively always on.

    Returns one vector per input. Empty input → empty output (no API call).
    """
    if not texts:
        return []
    return await embed_gemini(texts, task_type=_SIMILARITY_TASK)


def _unit_normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0.0:
        return v
    return [x / norm for x in v]


# ---- Gemini embeddings ----
#
# The single embedding backend for this service. `embed_batch`/`embed_batch_large`
# delegate here in the SEMANTIC_SIMILARITY space; `aio_proximity.py` uses the
# asymmetric retrieval spaces (headings as RETRIEVAL_QUERY, the AIO answer +
# fan-out questions as RETRIEVAL_DOCUMENT), which matches how Google scores AI
# Overview retrieval. Requires GEMINI_API_KEY — there is no OpenAI fallback.
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_GEMINI_BATCH_LIMIT = 100  # Gemini batchEmbedContents caps inputs per request


def gemini_configured() -> bool:
    return bool(settings.gemini_api_key)


async def embed_gemini(texts: list[str], *, task_type: str) -> list[list[float]]:
    """Embed texts with Gemini in the given retrieval space (RETRIEVAL_QUERY or
    RETRIEVAL_DOCUMENT), L2-normalized so cosine == dot product. Raises on a missing
    key or any API error so callers can fall back. Returns one vector per input."""
    if not texts:
        return []
    if not settings.gemini_api_key:
        raise RuntimeError("gemini_api_key_not_configured")

    model = settings.gemini_embedding_model
    model_path = model if model.startswith("models/") else f"models/{model}"
    url = f"{_GEMINI_BASE}/{model_path}:batchEmbedContents"
    headers = {"x-goog-api-key": settings.gemini_api_key}

    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for start in range(0, len(texts), _GEMINI_BATCH_LIMIT):
            chunk = texts[start:start + _GEMINI_BATCH_LIMIT]
            payload = {
                "requests": [
                    {
                        "model": model_path,
                        "content": {"parts": [{"text": t}]},
                        "taskType": task_type,
                        "outputDimensionality": settings.gemini_embedding_dim,
                    }
                    for t in chunk
                ]
            }
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings") or []
            if len(embeddings) != len(chunk):
                raise RuntimeError("gemini_embed_count_mismatch")
            # Gemini does not L2-normalize truncated (<3072-dim) outputs.
            out.extend(_unit_normalize([float(x) for x in e.get("values") or []]) for e in embeddings)
    return out


async def embed_gemini_query(texts: list[str]) -> list[list[float]]:
    return await embed_gemini(texts, task_type="RETRIEVAL_QUERY")


async def embed_gemini_document(texts: list[str]) -> list[list[float]]:
    return await embed_gemini(texts, task_type="RETRIEVAL_DOCUMENT")


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
