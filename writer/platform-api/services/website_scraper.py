"""Website scraping service — ScrapeOwl fetch + LLM extraction."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_SCRAPEOWL_URL = "https://api.scrapeowl.com/v1/scrape"

_SYSTEM_PROMPT = (
    "You extract structured business information from a website's homepage HTML. "
    "Return ONLY valid JSON matching the exact schema below — no prose, no markdown fences. "
    "If a field is unknown, use an empty array or empty string.\n\n"
    "Schema:\n"
    "{\n"
    '  "services": ["..."],\n'
    '  "locations": ["..."],\n'
    '  "contact_info": {\n'
    '    "phone": "...",\n'
    '    "email": "...",\n'
    '    "address": "...",\n'
    '    "hours": "..."\n'
    "  }\n"
    "}"
)


async def scrapeowl_fetch(url: str, timeout: int = 45) -> str:
    """Fetch raw HTML via ScrapeOwl."""
    payload = {
        "api_key": settings.scrapeowl_api_key,
        "url": url,
        "render_js": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(_SCRAPEOWL_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("html") or data.get("content") or ""


async def llm_extract_website_data(html: str) -> dict[str, Any]:
    """Call Claude to extract services/locations/contact_info from homepage HTML."""
    import anthropic

    # Truncate HTML to avoid exceeding context limits
    truncated_html = html[:40_000] if len(html) > 40_000 else html

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Extract business information from this homepage HTML:\n\n{truncated_html}",
            }
        ],
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("website_scraper.llm_json_parse_failed", extra={"raw_len": len(raw)})
        result = {"services": [], "locations": [], "contact_info": {}}

    return result
