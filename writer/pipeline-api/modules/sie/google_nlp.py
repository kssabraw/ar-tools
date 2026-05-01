"""Google Cloud Natural Language API client for SIE entity extraction.

Uses the REST API with an API key (GOOGLE_NLP_API_KEY) via httpx — no
service account JSON required.

Per SIE PRD Module 11 Pass 1: extract entities with salience >= 0.40, types
PERSON / LOCATION / ORGANIZATION / EVENT / WORK_OF_ART / CONSUMER_GOOD / OTHER.

Google's analyzeEntities endpoint accepts up to 100,000 bytes per call. We
truncate at the byte boundary to avoid mid-character splits.
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
SALIENCE_THRESHOLD = 0.40
ALLOWED_TYPES = {
    "PERSON", "LOCATION", "ORGANIZATION", "EVENT",
    "WORK_OF_ART", "CONSUMER_GOOD", "OTHER",
}
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
    lowered = name.lower().strip()
    if not lowered:
        return True
    if "." in lowered and len(lowered) < 30 and " " not in lowered:
        return True
    return any(p in lowered for p in NAVIGATIONAL_NAME_PATTERNS)


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

    entities: list[NEREntity] = []
    for entity in data.get("entities", []):
        if entity.get("salience", 0) < SALIENCE_THRESHOLD:
            continue
        type_name = entity.get("type", "OTHER")
        if type_name not in ALLOWED_TYPES:
            continue
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
