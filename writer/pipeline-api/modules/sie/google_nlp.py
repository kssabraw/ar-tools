"""Google Cloud Natural Language API client for SIE entity extraction.

Per SIE PRD Module 11 Pass 1: extract entities with salience >= 0.40, types
PERSON / LOCATION / ORGANIZATION / EVENT / WORK_OF_ART / CONSUMER_GOOD / OTHER.

Google's analyzeEntities endpoint accepts up to 100,000 bytes per call. We
truncate at the byte boundary to avoid mid-character splits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

GOOGLE_NLP_MAX_BYTES = 99_000  # leave a safety margin under the 100,000 cap
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


@lru_cache(maxsize=1)
def _client() -> Optional[object]:
    """Lazy-init the Google NLP client. Returns None if creds are missing."""
    creds_json = settings.google_nlp_credentials_json.strip()
    if not creds_json:
        logger.info("Google NLP credentials not configured — entity extraction disabled")
        return None
    try:
        from google.cloud import language_v1
        from google.oauth2 import service_account

        creds_dict = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(creds_dict)
        return language_v1.LanguageServiceClient(credentials=credentials)
    except Exception as exc:
        logger.error("Failed to init Google NLP client: %s", exc)
        return None


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    """Cut text to fit within a UTF-8 byte limit without splitting a codepoint."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")


def _is_navigational(name: str) -> bool:
    lowered = name.lower().strip()
    if not lowered or "." in lowered and len(lowered) < 30 and " " not in lowered:
        # Domain-name-like single tokens
        return True
    return any(p in lowered for p in NAVIGATIONAL_NAME_PATTERNS)


async def analyze_entities(url: str, text: str) -> PageNERResult:
    """Run analyzeEntities on a single page's cleaned body text."""
    if not text or not text.strip():
        return PageNERResult(url=url, failed=True, failure_reason="empty_text")

    client = _client()
    if client is None:
        return PageNERResult(url=url, failed=True, failure_reason="not_configured")

    # google-cloud-language is sync; run in a worker thread.
    payload_text = _truncate_to_bytes(text, GOOGLE_NLP_MAX_BYTES)
    try:
        response = await asyncio.to_thread(_invoke, client, payload_text)
    except Exception as exc:
        logger.warning("Google NLP call failed for %s: %s", url, exc)
        return PageNERResult(url=url, failed=True, failure_reason=f"api_error: {exc.__class__.__name__}")

    entities: list[NEREntity] = []
    for entity in response.entities:
        if entity.salience < SALIENCE_THRESHOLD:
            continue
        type_name = entity.type_.name if hasattr(entity, "type_") else str(entity.type)
        if type_name not in ALLOWED_TYPES:
            continue
        if _is_navigational(entity.name):
            continue
        entities.append(NEREntity(
            name=entity.name.strip(),
            type=type_name,
            salience=entity.salience,
            mentions=len(entity.mentions),
        ))
    return PageNERResult(url=url, entities=entities)


def _invoke(client, text: str):
    from google.cloud import language_v1
    document = language_v1.Document(
        content=text,
        type_=language_v1.Document.Type.PLAIN_TEXT,
        language="en",
    )
    return client.analyze_entities(
        request={"document": document, "encoding_type": language_v1.EncodingType.UTF8}
    )


async def analyze_many(pages: list[tuple[str, str]], concurrency: int = 5) -> list[PageNERResult]:
    """Run analyzeEntities on many (url, text) pairs concurrently."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(url: str, text: str) -> PageNERResult:
        async with semaphore:
            return await analyze_entities(url, text)

    return await asyncio.gather(*[_bounded(u, t) for u, t in pages])
