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


async def scrapeowl_fetch(
    url: str, timeout: int = 45, *, render_js: bool = False, premium: bool = False
) -> str:
    """Fetch raw HTML via ScrapeOwl.

    ``render_js`` runs the page's JavaScript before returning HTML; ``premium``
    routes through ScrapeOwl's premium residential proxies. Both default off
    (the cheap datacenter path); callers opt in — e.g. a reference-page scrape
    retries with both when a plain fetch comes back empty (bot-blocked)."""
    payload: dict[str, Any] = {
        "api_key": settings.scrapeowl_api_key,
        "url": url,
        "render_js": render_js,
    }
    if premium:
        payload["premium_proxies"] = True
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(_SCRAPEOWL_URL, json=payload)
        # Surface ScrapeOwl's own error message (it lives in the response body,
        # which raise_for_status() drops) so callers can log WHY a request was
        # rejected — e.g. an unsupported option or a rendering failure.
        if response.status_code >= 400:
            try:
                body = response.text[:400]
            except Exception:
                body = ""
            raise RuntimeError(f"scrapeowl HTTP {response.status_code}: {body}")
        data = response.json()
        return data.get("html") or data.get("content") or ""


async def llm_extract_website_data(html: str) -> dict[str, Any]:
    """Call the LLM to extract services/locations/contact_info from homepage HTML.

    Runs on Anthropic with automatic OpenAI→Gemini fallback on a transient
    (429/5xx/connection) failure via the shared report_llm layer."""
    from services import report_llm

    # Truncate HTML to avoid exceeding context limits
    truncated_html = html[:40_000] if len(html) > 40_000 else html

    raw = (await report_llm.generate_text(
        system=_SYSTEM_PROMPT,
        user=f"Extract business information from this homepage HTML:\n\n{truncated_html}",
        model="claude-sonnet-4-6",
        max_tokens=1024,
        log_tag="website_scraper",
    )).strip()
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
