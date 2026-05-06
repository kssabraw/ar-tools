"""TextRazor REST API client for SIE entity extraction (PRD v1.2).

TextRazor analyzes text and returns Wikipedia/DBpedia-linked entities
with `relevanceScore` (0-1) and `confidenceScore` (typically 0-10+).
We use it as a parallel signal to Google NLP - different vendor,
different training distribution, catches concepts Google NLP misses.

Free tier: 500 requests/day, no concurrency cap published. We bound
concurrency at 5 (matching the Google NLP wrapper) to stay polite and
avoid burning quota on retries.

API reference: https://www.textrazor.com/docs/rest

Authentication: requires `TEXTRAZOR_API_KEY` env var. Without it,
`analyze_entities` returns `PageTextRazorResult(failed=True,
failure_reason="not_configured")` so callers can fall back gracefully
without aborting the run.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


_TEXTRAZOR_URL = "https://api.textrazor.com/"
DEFAULT_TIMEOUT_SECONDS = 30.0
TEXTRAZOR_MAX_BYTES = 200_000  # TextRazor accepts up to ~200KB per request


# Map SIE's ISO-639-1 `language_code` (e.g. "en", "es", "fr") to
# TextRazor's 3-letter `languageOverride` codes. TextRazor supports
# 12+ languages but expects "eng" / "spa" / "fra" rather than ISO-1.
# Unmapped codes fall back to "eng" (TextRazor will still succeed -
# accuracy degrades gracefully on unsupported languages).
_TEXTRAZOR_LANGUAGE_MAP = {
    "en": "eng",
    "es": "spa",
    "fr": "fra",
    "de": "deu",
    "it": "ita",
    "pt": "por",
    "nl": "nld",
    "ja": "jpn",
    "zh": "zho",
    "ru": "rus",
    "pl": "pol",
    "tr": "tur",
}


def _textrazor_language(language_code: str) -> str:
    """Translate ISO-639-1 to TextRazor's 3-letter code; default to eng."""
    return _TEXTRAZOR_LANGUAGE_MAP.get(
        (language_code or "en").strip().lower(), "eng",
    )


class TextRazorError(Exception):
    """Raised on non-2xx HTTP responses or malformed payloads."""


@dataclass
class TextRazorEntity:
    """Per-occurrence record. Multiple occurrences across pages get
    aggregated downstream into a single deduplicated term."""

    name: str          # entityId (Wikipedia canonical), used for dedup
    matched_text: str  # the surface form as it appeared in the page
    relevance: float
    confidence: float
    type: list[str] = field(default_factory=list)
    wiki_link: Optional[str] = None
    starting_pos: int = 0
    ending_pos: int = 0


@dataclass
class PageTextRazorResult:
    url: str
    entities: list[TextRazorEntity] = field(default_factory=list)
    failed: bool = False
    failure_reason: Optional[str] = None


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


async def analyze_entities(
    url: str,
    text: str,
    *,
    http_client: Optional[httpx.AsyncClient] = None,
    language_code: str = "en",
) -> PageTextRazorResult:
    """Run TextRazor entity extraction on a single page's body text.

    Returns a `PageTextRazorResult` with `failed=True` and a reason when
    the API call doesn't succeed - callers should aggregate the
    successful results and ignore the failures (matching the Google NLP
    pattern).

    `language_code` is the SIE request's ISO-639-1 code; it gets
    translated to TextRazor's 3-letter `languageOverride`. Defaults to
    "en" so legacy callers keep working.
    """
    # Defensive - config defines `textrazor_api_key: str = ""`, but if
    # the field were missing or set to None the `.strip()` would
    # AttributeError.
    api_key = (getattr(settings, "textrazor_api_key", "") or "").strip()
    if not api_key:
        return PageTextRazorResult(
            url=url, failed=True, failure_reason="not_configured",
        )

    if not text or not text.strip():
        return PageTextRazorResult(
            url=url, failed=True, failure_reason="empty_text",
        )

    payload_text = _truncate_to_bytes(text, TEXTRAZOR_MAX_BYTES)
    # TextRazor uses form-encoded POST body, not JSON.
    form = {
        "text": payload_text,
        "extractors": "entities",  # explicitly request entities only
        "languageOverride": _textrazor_language(language_code),
    }
    headers = {
        "X-TextRazor-Key": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
    try:
        try:
            response = await client.post(_TEXTRAZOR_URL, data=form, headers=headers)
        except Exception as exc:
            logger.warning(
                "sie.textrazor.api_error",
                extra={"url": url, "error": str(exc)},
            )
            return PageTextRazorResult(
                url=url, failed=True,
                failure_reason=f"api_error: {exc.__class__.__name__}",
            )

        if response.status_code >= 400:
            body = response.text[:300]
            logger.warning(
                "sie.textrazor.http_error",
                extra={"url": url, "status": response.status_code, "body": body},
            )
            return PageTextRazorResult(
                url=url, failed=True,
                failure_reason=f"http_{response.status_code}",
            )

        try:
            data = response.json()
        except Exception as exc:
            return PageTextRazorResult(
                url=url, failed=True,
                failure_reason=f"non_json_response: {exc}",
            )
    finally:
        if owns_client:
            await client.aclose()

    response_obj = data.get("response") or {}
    entities_raw = response_obj.get("entities") or []
    entities: list[TextRazorEntity] = []
    for ent in entities_raw:
        if not isinstance(ent, dict):
            continue
        # TextRazor returns relevanceScore + confidenceScore at top level.
        # `entityId` is the canonical Wikipedia title; `matchedText` is
        # what actually appeared in the source. Prefer the canonical
        # form for dedup but keep matched_text for the variants list.
        entity_id = (ent.get("entityId") or ent.get("matchedText") or "").strip()
        matched = (ent.get("matchedText") or entity_id).strip()
        if not entity_id:
            continue
        try:
            relevance = float(ent.get("relevanceScore", 0.0))
            confidence = float(ent.get("confidenceScore", 0.0))
        except (TypeError, ValueError):
            continue
        types = ent.get("type") or []
        if not isinstance(types, list):
            types = []
        entities.append(TextRazorEntity(
            name=entity_id,
            matched_text=matched,
            relevance=relevance,
            confidence=confidence,
            type=[str(t) for t in types if t],
            wiki_link=ent.get("wikiLink"),
            starting_pos=int(ent.get("startingPos", 0) or 0),
            ending_pos=int(ent.get("endingPos", 0) or 0),
        ))

    return PageTextRazorResult(url=url, entities=entities)


async def analyze_many(
    pages: list[tuple[str, str]],
    *,
    concurrency: int = 2,
    language_code: str = "en",
) -> list[PageTextRazorResult]:
    """Run analyze_entities on many (url, text) pairs concurrently.

    Concurrency defaults to 2 to stay under TextRazor free-tier's
    per-second concurrency cap (~3 simultaneous requests). Earlier
    runs with concurrency=5 produced a storm of 401 Unauthorized
    responses interleaved with 200s - TextRazor's free tier returns
    401 (rather than the documented 429) when concurrency is
    exceeded. Lowering to 2 fits comfortably under the limit at the
    cost of slightly longer total latency on a 20-page corpus.

    A single shared `httpx.AsyncClient` is used across all calls so we
    benefit from connection pooling - without this, each per-page call
    spins up its own client (N TLS handshakes for N pages).
    """
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        async def _bounded(url: str, text: str) -> PageTextRazorResult:
            async with semaphore:
                return await analyze_entities(
                    url, text,
                    http_client=client,
                    language_code=language_code,
                )

        return await asyncio.gather(*[_bounded(u, t) for u, t in pages])
