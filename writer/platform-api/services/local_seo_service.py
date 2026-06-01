"""Local SEO module (#2) — orchestration over the private nlp service.

platform-api owns auth + persistence; the nlp service (Railway private
network) does the analysis/generation. We build the generation payload from
the client's stored GBP data, stream the nlp `/generate-page` SSE response,
and persist the result to `local_seo_pages`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Generation can take minutes (SERP scrape + Claude + scoring + reoptimize).
_GENERATE_TIMEOUT = 600


def _gbp_to_generate_payload(client: dict, keyword: str, location: str, run_analysis: bool) -> dict:
    """Map a suite client row (with its `gbp` JSONB) to the nlp service's
    GeneratePageRequest. Brand-voice / ICP fields are intentionally omitted
    (cut from this version), so the nlp service handles their absence."""
    gbp = client.get("gbp") or {}
    hours = gbp.get("hours")
    return {
        "keyword": keyword,
        "location": location,
        "business_name": gbp.get("business_name") or client.get("name") or "",
        "gbp_category": gbp.get("gbp_category") or "",
        "address": gbp.get("address") or client.get("business_location") or "",
        "phone": gbp.get("phone"),
        "website": gbp.get("website") or client.get("website_url"),
        "hours": json.dumps(hours) if hours else None,
        "gbp_description": gbp.get("description"),
        "reviews": gbp.get("reviews") or None,
        "run_analysis": run_analysis,
    }


async def _stream_generate(payload: dict) -> dict:
    """POST to the nlp `/generate-page` SSE endpoint and return the final
    `result` dict. Raises HTTPException on provider error / no result."""
    url = f"{settings.nlp_api_url}/generate-page"
    result: Optional[dict] = None
    try:
        async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.warning(
                        "local_seo.generate_http_error",
                        extra={"status_code": response.status_code, "body": body[:500]},
                    )
                    raise HTTPException(status_code=502, detail="local_seo_provider_error")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[len("data:"):].strip())
                    except json.JSONDecodeError:
                        continue
                    step = event.get("step")
                    if step == "error":
                        logger.warning(
                            "local_seo.generate_worker_error",
                            extra={"message": event.get("message")},
                        )
                        raise HTTPException(status_code=502, detail="local_seo_generation_failed")
                    if step == "done":
                        result = event.get("result")
    except httpx.HTTPError as exc:
        logger.warning("local_seo.generate_request_error", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="local_seo_provider_error") from exc

    if not result:
        raise HTTPException(status_code=502, detail="local_seo_no_result")
    return result


async def generate_page(client_id: str, keyword: str, location: str, run_analysis: bool, user_id: str) -> dict:
    """Generate a local SEO page for a client and persist it. Returns the
    stored `local_seo_pages` row."""
    supabase = get_supabase()

    client_res = (
        supabase.table("clients").select("*").eq("id", client_id).single().execute()
    )
    if not client_res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = client_res.data

    payload = _gbp_to_generate_payload(client, keyword, location, run_analysis)
    result = await _stream_generate(payload)

    composite_score = result.get("composite_score")
    row = {
        "client_id": client_id,
        "keyword": keyword,
        "location": location,
        "run_analysis": run_analysis,
        "content_html": result.get("content_html") or "",
        "schema_json": result.get("schema_json") or "",
        "page_title": result.get("page_title"),
        "content_gaps": result.get("content_gaps") or [],
        "composite_score": composite_score,
        "composite_status": result.get("composite_status"),
        "mode": "generate",
        "token_usage": result.get("token_usage"),
        "cost_breakdown": result.get("cost_breakdown"),
        "created_by": user_id,
    }
    insert = supabase.table("local_seo_pages").insert(row).execute()
    page = insert.data[0]
    logger.info(
        "local_seo.page_generated",
        extra={"client_id": client_id, "page_id": page["id"], "run_analysis": run_analysis},
    )
    return page


def list_pages(client_id: str) -> list[dict]:
    supabase = get_supabase()
    res = (
        supabase.table("local_seo_pages")
        .select("id, client_id, keyword, location, page_title, composite_score, composite_status, mode, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def get_page(page_id: str) -> dict:
    supabase = get_supabase()
    res = supabase.table("local_seo_pages").select("*").eq("id", page_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="local_seo_page_not_found")
    return res.data
