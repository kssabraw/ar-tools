"""Local SEO module (#2) — orchestration over the private nlp service.

platform-api owns auth + persistence; the nlp service (Railway private
network) does the analysis/generation/scoring. We build payloads from the
client's stored GBP data, call the nlp endpoints, and persist generated /
reoptimized pages to `local_seo_pages`.

The nlp service is private + auth-less, so every call here is a server-side
proxy: the frontend never reaches nlp directly.
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

# Generation/reoptimization can take minutes (SERP scrape + Claude + scoring).
_GENERATE_TIMEOUT = 600
# Plain JSON endpoints (analyze / find-page / score / related / social) are
# faster but still scrape/score — give them generous headroom.
_JSON_TIMEOUT = 300


# ── client → nlp payload helpers ────────────────────────────────────────────

def _get_client(client_id: str) -> dict:
    supabase = get_supabase()
    res = supabase.table("clients").select("*").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data


def _business_fields(client: dict) -> dict:
    """Common business identity fields the nlp endpoints expect, sourced from
    the client's GBP record with sensible client-row fallbacks."""
    gbp = client.get("gbp") or {}
    return {
        "business_name": gbp.get("business_name") or client.get("name") or "",
        "gbp_category": gbp.get("gbp_category") or "",
        "address": gbp.get("address") or client.get("business_location") or "",
        "phone": gbp.get("phone"),
        "website": gbp.get("website") or client.get("website_url"),
    }


def _gbp_to_generate_payload(client: dict, keyword: str, location: str, run_analysis: bool) -> dict:
    """Map a suite client row (with its `gbp` JSONB) to the nlp service's
    GeneratePageRequest. Brand-voice / ICP fields are intentionally omitted
    (cut from this version), so the nlp service handles their absence."""
    gbp = client.get("gbp") or {}
    hours = gbp.get("hours")
    fields = _business_fields(client)
    return {
        "keyword": keyword,
        "location": location,
        "business_name": fields["business_name"],
        "gbp_category": fields["gbp_category"],
        "address": fields["address"],
        "phone": fields["phone"],
        "website": fields["website"],
        "hours": json.dumps(hours) if hours else None,
        "gbp_description": gbp.get("description"),
        "reviews": gbp.get("reviews") or None,
        "run_analysis": run_analysis,
    }


# ── nlp transport ───────────────────────────────────────────────────────────

async def _post_nlp(
    path: str, payload: dict, timeout: int = _JSON_TIMEOUT, user_id: Optional[str] = None
) -> dict:
    """POST to a plain-JSON nlp endpoint and return the parsed body.

    When `user_id` is supplied it's forwarded as `X-User-ID` so the nlp
    rate limiter keys per end user instead of per (single) platform-api caller
    IP — see `_real_client_ip` in nlp-api/main.py.
    """
    url = f"{settings.nlp_api_url}{path}"
    headers = {"X-User-ID": user_id} if user_id else None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                logger.warning(
                    "local_seo.nlp_http_error",
                    extra={"path": path, "status_code": response.status_code, "body": response.text[:500]},
                )
                raise HTTPException(status_code=502, detail="local_seo_provider_error")
            try:
                return response.json()
            except ValueError as exc:
                # 200 with a non-JSON / truncated body (e.g. a proxy error page).
                # Map to a provider error rather than letting it surface as 500.
                logger.warning(
                    "local_seo.nlp_decode_error",
                    extra={"path": path, "body": response.text[:500]},
                )
                raise HTTPException(status_code=502, detail="local_seo_provider_error") from exc
    except httpx.HTTPError as exc:
        logger.warning("local_seo.nlp_request_error", extra={"path": path, "error": str(exc)})
        raise HTTPException(status_code=502, detail="local_seo_provider_error") from exc


async def _stream_nlp(path: str, payload: dict) -> dict:
    """POST to an SSE nlp endpoint (`/generate-page`, `/reoptimize-page`) and
    return the final `result` dict. Raises HTTPException on provider error."""
    url = f"{settings.nlp_api_url}{path}"
    result: Optional[dict] = None
    try:
        async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.warning(
                        "local_seo.stream_http_error",
                        extra={"path": path, "status_code": response.status_code, "body": body[:500]},
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
                            "local_seo.stream_worker_error",
                            extra={"path": path, "message": event.get("message")},
                        )
                        raise HTTPException(status_code=502, detail="local_seo_generation_failed")
                    if step == "done":
                        result = event.get("result")
    except httpx.HTTPError as exc:
        logger.warning("local_seo.stream_request_error", extra={"path": path, "error": str(exc)})
        raise HTTPException(status_code=502, detail="local_seo_provider_error") from exc

    if not result:
        raise HTTPException(status_code=502, detail="local_seo_no_result")
    return result


# ── persistence ─────────────────────────────────────────────────────────────

def _persist_page(client_id: str, keyword: str, location: str, run_analysis: bool, mode: str, result: dict, user_id: str) -> dict:
    row = {
        "client_id": client_id,
        "keyword": keyword,
        "location": location,
        "run_analysis": run_analysis,
        "content_html": result.get("content_html") or "",
        "schema_json": result.get("schema_json") or "",
        "page_title": result.get("page_title"),
        "content_gaps": result.get("content_gaps") or [],
        "composite_score": result.get("composite_score"),
        "composite_status": result.get("composite_status"),
        "mode": mode,
        "token_usage": result.get("token_usage"),
        "cost_breakdown": result.get("cost_breakdown"),
        "created_by": user_id,
    }
    insert = get_supabase().table("local_seo_pages").insert(row).execute()
    page = insert.data[0]
    logger.info(
        "local_seo.page_persisted",
        extra={"client_id": client_id, "page_id": page["id"], "mode": mode, "run_analysis": run_analysis},
    )
    return page


# ── public operations ───────────────────────────────────────────────────────

async def generate_page(client_id: str, keyword: str, location: str, run_analysis: bool, user_id: str) -> dict:
    """Generate a local SEO page for a client and persist it."""
    client = _get_client(client_id)
    payload = _gbp_to_generate_payload(client, keyword, location, run_analysis)
    result = await _stream_nlp("/generate-page", payload)
    return _persist_page(client_id, keyword, location, run_analysis, "generate", result, user_id)


async def analyze(client_id: str, keyword: str, location: str, location_code: Optional[int]) -> dict:
    """Run competitor SERP analysis for a keyword + location (no persistence)."""
    _get_client(client_id)  # validate ownership / existence
    return await _post_nlp("/analyze", {
        "keyword": keyword,
        "location": location,
        "location_code": location_code,
    })


async def find_page(client_id: str, keyword: str, location: str) -> dict:
    """Scan the client's website for an existing page targeting the keyword."""
    client = _get_client(client_id)
    website = _business_fields(client)["website"]
    if not website:
        raise HTTPException(status_code=400, detail="client_has_no_website")
    return await _post_nlp("/find-page-for-keyword", {
        "website_url": website,
        "keyword": keyword,
        "location": location,
    })


async def score_page(
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    page_url: Optional[str],
    page_content: Optional[str],
    serp_analysis: Optional[dict],
) -> dict:
    """Score an existing page (by URL or raw HTML) against the 8 engines."""
    client = _get_client(client_id)
    fields = _business_fields(client)
    if not page_url and not page_content:
        raise HTTPException(status_code=400, detail="page_url_or_content_required")
    return await _post_nlp("/score-page", {
        "keyword": keyword,
        "location": location,
        "location_code": location_code,
        "page_url": page_url,
        "page_content": page_content,
        "business_name": fields["business_name"],
        "gbp_category": fields["gbp_category"],
        "address": fields["address"],
        "serp_analysis": serp_analysis,
    })


async def related_pages(client_id: str, keyword: str, location: str) -> dict:
    """Discover parent/sibling/child page opportunities for a keyword."""
    client = _get_client(client_id)
    fields = _business_fields(client)
    return await _post_nlp("/related-pages", {
        "keyword": keyword,
        "location": location,
        "business_name": fields["business_name"],
        "gbp_category": fields["gbp_category"],
        "address": fields["address"],
        "website": fields["website"],
    })


async def reoptimize_page(
    client_id: str,
    keyword: str,
    location: str,
    existing_page_html: Optional[str],
    existing_page_url: Optional[str],
    deficiencies: list[dict],
    serp_analysis: Optional[dict],
    user_id: str,
) -> dict:
    """Reoptimize an existing page to lift its score, re-score the result, and
    persist it as a `mode='reoptimize'` row."""
    client = _get_client(client_id)
    fields = _business_fields(client)
    if not existing_page_html and not existing_page_url:
        raise HTTPException(status_code=400, detail="page_url_or_html_required")

    result = await _stream_nlp("/reoptimize-page", {
        "keyword": keyword,
        "location": location,
        "existing_page_html": existing_page_html,
        "existing_page_url": existing_page_url,
        "deficiencies": deficiencies,
        "business_name": fields["business_name"],
        "gbp_category": fields["gbp_category"],
        "address": fields["address"],
        "phone": fields["phone"],
        "serp_analysis": serp_analysis,
    })

    # Newer nlp builds surface the score the reoptimize loop already computed.
    # Only re-score when it's absent (older nlp) so the persisted page still
    # reflects the lifted score — avoids a redundant second scoring LLM call.
    if result.get("composite_score") is None:
        try:
            score = await _post_nlp("/score-page", {
                "keyword": keyword,
                "location": location,
                "page_content": result.get("content_html"),
                "business_name": fields["business_name"],
                "gbp_category": fields["gbp_category"],
                "address": fields["address"],
                "serp_analysis": serp_analysis,
            })
            result["composite_score"] = score.get("composite_score")
            result["composite_status"] = score.get("composite_status")
        except Exception:
            # Non-fatal — the expensive rewrite already succeeded, so persist the
            # reoptimized page without a fresh score rather than losing the work.
            # (Catches HTTPException from the proxy AND any decode/unexpected error.)
            logger.warning("local_seo.reoptimize_rescore_failed", extra={"client_id": client_id})

    return _persist_page(client_id, keyword, location, bool(serp_analysis), "reoptimize", result, user_id)


async def social_posts(
    client_id: str,
    keyword: str,
    location: str,
    page_content: str,
    serp_analysis: Optional[dict],
) -> dict:
    """Generate GBP social posts from a generated page's text."""
    client = _get_client(client_id)
    fields = _business_fields(client)
    return await _post_nlp("/generate-social-posts", {
        "keyword": keyword,
        "location": location,
        "business_name": fields["business_name"],
        "gbp_category": fields["gbp_category"],
        "address": fields["address"],
        "phone": fields["phone"],
        "page_content": page_content,
        "serp_analysis": serp_analysis,
    })


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


def delete_page(page_id: str) -> None:
    supabase = get_supabase()
    res = supabase.table("local_seo_pages").delete().eq("id", page_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="local_seo_page_not_found")
    logger.info("local_seo.page_deleted", extra={"page_id": page_id})
