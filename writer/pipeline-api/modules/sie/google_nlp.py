"""Google Cloud Natural Language API client for SIE entity extraction.

Uses the REST API with an API key (GOOGLE_NLP_API_KEY) via httpx — no
service account JSON required.

SIE v1.1 (replaces v1.0's hard salience >= 0.40 gate):
  - Salience floor lowered to `google_nlp_min_salience_floor` (default
    0.10) so low-salience entities with cross-SERP recurrence aren't
    discarded at extraction time. Hybrid scoring in `entities.py`
    promotes them based on the composite signal.
  - Type whitelist removed — every Google NLP entity type passes
    through the extractor. NUMBER / DATE / PRICE / PHONE_NUMBER
    entities are filtered downstream by the noise penalty in the
    composite score (typically low salience + low recurrence anyway).
  - Navigational-name heuristic is preserved (catches obvious junk
    before it ever reaches scoring).

Google's analyzeEntities endpoint accepts up to 100,000 bytes per call.
We truncate at the byte boundary to avoid mid-character splits.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_NLP_URL = "https://language.googleapis.com/v1/documents:analyzeEntities"
GOOGLE_NLP_MAX_BYTES = 99_000

NAVIGATIONAL_NAME_PATTERNS = (
    "menu", "navigation", "homepage", "facebook", "twitter",
    "instagram", "linkedin", "youtube", "tiktok", "search",
    "subscribe", "newsletter", "login", "register",
)


@dataclass
class NEREntity:
    name: str
    type: str
    salience: float
    mentions: int = 1


@dataclass
class PageNERResult:
    url: str
    entities: list[NEREntity] = field(default_factory=list)
    failed: bool = False
    failure_reason: Optional[str] = None


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _is_navigational(name: str) -> bool:
    """True when `name` looks like menu/footer junk rather than content.

    SIE v1.1 — tightened from substring match to exact-token match so
    legitimate entities containing a navigational word as part of their
    proper noun ("TikTok Shop", "Facebook Marketing Strategy") are NOT
    filtered. Only entities whose entire name IS one of the patterns
    (or a bare domain) are dropped here. Anything subtler is handled
    downstream by the composite-score noise penalty in `entities.py`.
    """
    lowered = name.lower().strip()
    if not lowered:
        return True
    # Bare domain: dot-separated, short, no spaces (e.g. "tiktok.com")
    if "." in lowered and len(lowered) < 30 and " " not in lowered:
        return True
    # Exact match against the navigational pattern list.
    return lowered in NAVIGATIONAL_NAME_PATTERNS


async def analyze_entities(url: str, text: str) -> PageNERResult:
    """Run analyzeEntities on a single page's cleaned body text."""
    api_key = settings.google_nlp_api_key.strip()
    if not api_key:
        logger.info("Google NLP API key not configured — entity extraction disabled")
        return PageNERResult(url=url, failed=True, failure_reason="not_configured")

    if not text or not text.strip():
        return PageNERResult(url=url, failed=True, failure_reason="empty_text")

    payload_text = _truncate_to_bytes(text, GOOGLE_NLP_MAX_BYTES)
    body = {
        "document": {"content": payload_text, "type": "PLAIN_TEXT", "language": "en"},
        "encodingType": "UTF8",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                _NLP_URL,
                params={"key": api_key},
                json=body,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Google NLP HTTP error for %s: %s", url, exc.response.text[:200])
        return PageNERResult(url=url, failed=True, failure_reason=f"http_{exc.response.status_code}")
    except Exception as exc:
        logger.warning("Google NLP call failed for %s: %s", url, exc)
        return PageNERResult(url=url, failed=True, failure_reason=f"api_error: {exc.__class__.__name__}")

    floor = settings.google_nlp_min_salience_floor
    entities: list[NEREntity] = []
    for entity in data.get("entities", []):
        # SIE v1.1 — soft salience floor (default 0.10) replaces the
        # prior hard 0.40 gate. Entities surviving here are scored
        # downstream against recurrence + mentions before promotion.
        if entity.get("salience", 0) < floor:
            continue
        type_name = entity.get("type", "OTHER")
        name = (entity.get("name") or "").strip()
        if _is_navigational(name):
            continue
        entities.append(NEREntity(
            name=name,
            type=type_name,
            salience=entity["salience"],
            mentions=len(entity.get("mentions", [])) or 1,
        ))

    return PageNERResult(url=url, entities=entities)


async def analyze_many(pages: list[tuple[str, str]], concurrency: int = 5) -> list[PageNERResult]:
    """Run analyzeEntities on many (url, text) pairs concurrently."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(url: str, text: str) -> PageNERResult:
        async with semaphore:
            return await analyze_entities(url, text)

    return await asyncio.gather(*[_bounded(u, t) for u, t in pages])
