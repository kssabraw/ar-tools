"""DataForSEO API client.

Endpoints used by the Brief Generator:
- SERP organic (live, depth=20) - Step 1 SERP scrape
- SERP organic (live) with `site:reddit.com` - Step 2B Reddit search
- Autocomplete (live) - Step 2C
- Keyword Suggestions (DataForSEO Labs, live) - Step 2C
- LLM Responses (live) for ChatGPT/Claude/Gemini/Perplexity - Step 2D

All calls use HTTP Basic Auth with login + password from env vars.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import secrets
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dataforseo.com"
DEFAULT_TIMEOUT = 60.0
DEFAULT_LANGUAGE_CODE = "en"
DEFAULT_LOCATION_CODE = 2840  # United States

# DataForSEO status-code convention: 20000 = ok, 40000-49999 = client/task
# errors (bad request, invalid keyword, no results — permanent), 50000+ =
# server-side errors ("Internal Error" / "Internal SE Server Error" — transient,
# clear on a re-set after a short delay).
_DFS_SERVER_ERROR_FLOOR = 50000
_DFS_ERROR_FLOOR = 40000


class DataForSEOError(Exception):
    """Raised when DataForSEO returns an unexpected response.

    `retryable` marks the transient server-side band (status_code >= 50000) so
    `_post` retries it; client/task errors are permanent and raised immediately.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


def _is_transient_dataforseo_error(exc: Exception) -> bool:
    """Retryable DataForSEO failures: server-side task errors (status_code
    >= 50000), HTTP 5xx, and timeouts / connection drops. Client errors (4xx,
    status_code 40000-49999) fail fast — a retry can't fix a bad keyword or a
    404 endpoint."""
    if isinstance(exc, DataForSEOError):
        return exc.retryable
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    return False


async def _request_once(path: str, payload: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
    """One POST to DataForSEO returning the parsed first task result.

    DataForSEO wraps everything in a tasks[] array even for single requests.
    """
    url = f"{BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=_auth_header(), json=payload)
        response.raise_for_status()
        body = response.json()

    body_status = body.get("status_code")
    if body_status and body_status >= _DFS_ERROR_FLOOR:
        raise DataForSEOError(
            f"{path}: {body.get('status_message')}",
            retryable=body_status >= _DFS_SERVER_ERROR_FLOOR,
        )

    tasks = body.get("tasks") or []
    if not tasks:
        raise DataForSEOError(f"{path}: no tasks in response")

    task = tasks[0]
    task_status = task.get("status_code")
    if task_status and task_status >= _DFS_ERROR_FLOOR:
        raise DataForSEOError(
            f"{path}: task error {task.get('status_message')}",
            retryable=task_status >= _DFS_SERVER_ERROR_FLOOR,
        )

    return task


async def _post(path: str, payload: list[dict[str, Any]], timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """POST to DataForSEO with transient-error retries (exponential backoff +
    jitter). Only the transient band is retried; permanent client/task errors
    raise on the first attempt. See `dataforseo_max_retries` in config."""
    attempt = 0
    while True:
        try:
            return await _request_once(path, payload, timeout)
        except Exception as exc:  # noqa: BLE001 — classify, re-raise if terminal
            if attempt >= settings.dataforseo_max_retries or not _is_transient_dataforseo_error(exc):
                raise
            delay = settings.dataforseo_retry_base_seconds * (2 ** attempt) * (
                0.5 + secrets.randbelow(1000) / 1000.0
            )
            logger.warning(
                "dataforseo_transient_retry",
                extra={
                    "path": path,
                    "attempt": attempt + 1,
                    "delay_s": round(delay, 1),
                    "error": str(exc)[:200],
                },
            )
            await asyncio.sleep(delay)
            attempt += 1


async def serp_organic_advanced(
    keyword: str,
    location_code: int = DEFAULT_LOCATION_CODE,
    depth: int = 20,
) -> dict[str, Any]:
    """Step 1 - Top 20 organic results, plus PAA, related searches, SERP features."""
    payload = [
        {
            "keyword": keyword,
            "language_code": DEFAULT_LANGUAGE_CODE,
            "location_code": location_code,
            "depth": depth,
            "calculate_rectangles": False,
        }
    ]
    task = await _post("/v3/serp/google/organic/live/advanced", payload)
    items = (task.get("result") or [{}])[0].get("items") or []
    return {"task": task, "items": items}


async def serp_reddit(
    keyword: str,
    location_code: int = DEFAULT_LOCATION_CODE,
    depth: int = 5,
) -> list[dict[str, Any]]:
    """Step 2B - Top Reddit threads via `site:reddit.com` query."""
    payload = [
        {
            "keyword": f"{keyword} site:reddit.com",
            "language_code": DEFAULT_LANGUAGE_CODE,
            "location_code": location_code,
            "depth": depth,
        }
    ]
    task = await _post("/v3/serp/google/organic/live/advanced", payload)
    items = (task.get("result") or [{}])[0].get("items") or []
    return [item for item in items if item.get("type") == "organic"][:depth]


async def autocomplete(
    keyword: str,
    location_code: int = DEFAULT_LOCATION_CODE,
) -> list[str]:
    """Step 2C - Google Autocomplete suggestions."""
    payload = [
        {
            "keyword": keyword,
            "language_code": DEFAULT_LANGUAGE_CODE,
            "location_code": location_code,
        }
    ]
    task = await _post("/v3/serp/google/autocomplete/live/advanced", payload)
    items = (task.get("result") or [{}])[0].get("items") or []
    return [item["suggestion"] for item in items if item.get("suggestion")]


async def keyword_suggestions(
    keyword: str,
    location_code: int = DEFAULT_LOCATION_CODE,
    limit: int = 50,
) -> list[str]:
    """Step 2C - DataForSEO Labs keyword suggestions."""
    payload = [
        {
            "keyword": keyword,
            "language_code": DEFAULT_LANGUAGE_CODE,
            "location_code": location_code,
            "limit": limit,
            "include_seed_keyword": False,
        }
    ]
    task = await _post("/v3/dataforseo_labs/google/keyword_suggestions/live", payload)
    items = (task.get("result") or [{}])[0].get("items") or []
    return [item["keyword"] for item in items if item.get("keyword")]


# ---- LLM Responses (Step 2D) ----

LLM_FANOUT_PROMPT = (
    "What are the most important subtopics and questions someone "
    "should understand about {keyword}?"
)


async def llm_response(
    keyword: str,
    model: str,
    web_search: bool = True,
    force_web_search: bool = False,
    location_iso: str = "US",
    max_output_tokens: int = 500,
) -> dict[str, Any]:
    """Step 2D - single LLM fan-out call via DataForSEO LLM Responses API.

    Returns dict with keys: text, fan_out_queries (list of strings).
    Raises DataForSEOError on failure so caller can flag the LLM as unavailable.
    """
    body: dict[str, Any] = {
        "user_prompt": LLM_FANOUT_PROMPT.format(keyword=keyword),
        "model_name": model,
        "max_output_tokens": max_output_tokens,
        "web_search": web_search,
    }
    if force_web_search:
        body["force_web_search"] = True
    if location_iso:
        body["web_search_country_iso_code"] = location_iso

    task = await _post("/v3/ai_optimization/llm_responses/live", [body])
    result = (task.get("result") or [{}])[0]

    text = result.get("response_text") or result.get("text") or ""
    fan_out = result.get("fan_out_queries") or []
    fan_out_strs = [
        q if isinstance(q, str) else q.get("query", "")
        for q in fan_out
    ]
    fan_out_strs = [q for q in fan_out_strs if q]

    return {"text": text, "fan_out_queries": fan_out_strs}
