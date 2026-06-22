"""Local SEO module (#2) — orchestration over the private nlp service.

platform-api owns auth + persistence; the nlp service (Railway private
network) does the analysis/generation/scoring. We build payloads from the
client's stored GBP data, call the nlp endpoints, and persist generated /
reoptimized pages to `local_seo_pages`.

The nlp service is private + auth-less, so every call here is a server-side
proxy: the frontend never reaches nlp directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import analysis_cache, locations_service
from services.html_to_markdown import html_to_markdown

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


def _gbp_to_generate_payload(
    client: dict, keyword: str, location: str, run_analysis: bool, location_code: Optional[int] = None
) -> dict:
    """Map a suite client row (with its `gbp` JSONB) to the nlp service's
    GeneratePageRequest. The converged brand_voice / detected_icp /
    differentiators assets are passed through so the generator targets the
    client's voice and customers; the nlp service handles their absence."""
    gbp = client.get("gbp") or {}
    hours = gbp.get("hours")
    fields = _business_fields(client)
    return {
        "keyword": keyword,
        "location": location,
        "location_code": location_code,
        "business_name": fields["business_name"],
        "gbp_category": fields["gbp_category"],
        "address": fields["address"],
        "phone": fields["phone"],
        "website": fields["website"],
        "hours": json.dumps(hours) if hours else None,
        "gbp_description": gbp.get("description"),
        "reviews": gbp.get("reviews") or None,
        "run_analysis": run_analysis,
        "brand_voice": client.get("brand_voice"),
        "detected_icp": client.get("detected_icp"),
        "differentiators": client.get("differentiators") or [],
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

async def search_locations(client_id: str, query: str, country: Optional[str] = None) -> list[dict]:
    """Typeahead suggestions for the area field, scoped to the client's country."""
    client = _get_client(client_id)
    return await locations_service.search_locations(client, query, country=country)


# Per-key locks collapse concurrent identical cache misses into a single compute
# (single-flight). Effective because the platform-api runs a single replica; a
# second caller for the same key waits, then gets the just-stored result.
_analysis_locks: dict[str, asyncio.Lock] = {}


def _analysis_lock(key: str) -> asyncio.Lock:
    lock = _analysis_locks.get(key)
    if lock is None:
        lock = _analysis_locks.setdefault(key, asyncio.Lock())
    return lock


async def _compute_and_store(
    keyword: str, location: str, location_code: Optional[int], user_id: Optional[str], required: bool,
) -> Optional[dict]:
    """Run the nlp SERP analysis and cache it. On provider failure: re-raise when
    `required` (the analysis IS the deliverable), else log and return None so the
    caller can degrade gracefully (generate/score are enhanced by analysis, not
    gated on it)."""
    try:
        result = await _post_nlp("/analyze", {
            "keyword": keyword,
            "location": location,
            "location_code": location_code,
        }, user_id=user_id)
    except HTTPException as exc:
        if required:
            raise
        logger.warning(
            "local_seo.analysis_degraded",
            extra={"keyword": keyword, "location": location, "detail": getattr(exc, "detail", None)},
        )
        return None
    analysis_cache.store(keyword, location_code, location, result)
    return result


async def _get_or_compute_analysis(
    keyword: str,
    location: str,
    location_code: Optional[int],
    force_refresh: bool,
    user_id: Optional[str] = None,
    required: bool = True,
) -> Optional[dict]:
    """Return a SERP analysis for (keyword, location), served from the shared
    cache when fresh (within the TTL) — otherwise run the nlp pipeline once and
    cache the result. `force_refresh` bypasses the cache for a re-scrape;
    `required=False` degrades to None on provider failure instead of raising."""
    if force_refresh:
        return await _compute_and_store(keyword, location, location_code, user_id, required)

    cached = analysis_cache.get(keyword, location_code, location)
    if cached is not None:
        return cached
    # Miss → single-flight so concurrent identical requests don't all re-scrape.
    async with _analysis_lock(analysis_cache.cache_key(keyword, location_code, location)):
        cached = analysis_cache.get(keyword, location_code, location)
        if cached is not None:
            return cached
        return await _compute_and_store(keyword, location, location_code, user_id, required)


def set_page_template_default(client_id: str, page_template_url: Optional[str]) -> dict:
    """Persist the client's default Local SEO page-template URL (Phase 3)."""
    url = (page_template_url or "").strip() or None
    supabase = get_supabase()
    res = (
        supabase.table("clients")
        .update({"local_seo_page_template_url": url, "updated_at": "now()"})
        .eq("id", client_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    logger.info("local_seo.page_template_default_set", extra={"client_id": client_id, "set": bool(url)})
    return {"local_seo_page_template_url": url}


async def generate_page(
    client_id: str, keyword: str, location: str, location_code: Optional[int],
    run_analysis: bool, user_id: str, force_refresh: bool = False,
    page_template_url: Optional[str] = None,
) -> dict:
    """Generate a local SEO page for a client and persist it.

    The location is resolved/validated first: a mistyped area (no picked code)
    that can't be matched fails loudly (400). When analysis is requested it's
    pulled from the shared cache (or computed + cached once) and passed to nlp so
    the generator doesn't re-scrape. If the analysis itself fails (e.g. thin SERP
    / provider outage), generation degrades to a no-competitor page rather than
    failing outright — and run_analysis is flipped off in the nlp payload so nlp
    doesn't re-attempt the same failing scrape."""
    client = _get_client(client_id)
    location, location_code = await locations_service.resolve_location(client, location, location_code)
    payload = _gbp_to_generate_payload(client, keyword, location, run_analysis, location_code)
    # Page template: per-page value wins; otherwise the client's saved default.
    template_url = (page_template_url or "").strip() or client.get("local_seo_page_template_url")
    if template_url:
        payload["page_template_url"] = template_url
    if run_analysis:
        serp = await _get_or_compute_analysis(
            keyword, location, location_code, force_refresh, user_id, required=False
        )
        if serp is not None:
            payload["serp_analysis"] = serp
        else:
            payload["run_analysis"] = False  # analysis unavailable → degrade, no nlp re-scrape
    result = await _stream_nlp("/generate-page", payload)
    return _persist_page(client_id, keyword, location, run_analysis, "generate", result, user_id)


async def analyze(
    client_id: str, keyword: str, location: str, location_code: Optional[int], force_refresh: bool = False,
) -> dict:
    """Run (or reuse a cached) competitor SERP analysis for a keyword + location.

    Here the analysis IS the deliverable, so a provider failure propagates
    (required=True) instead of degrading."""
    client = _get_client(client_id)  # validate ownership / existence
    location, location_code = await locations_service.resolve_location(client, location, location_code)
    result = await _get_or_compute_analysis(keyword, location, location_code, force_refresh, required=True)
    assert result is not None  # required=True never returns None (it raises)
    return result


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
    user_id: Optional[str] = None,
    force_refresh: bool = False,
) -> dict:
    """Score an existing page (by URL or raw HTML) against the 8 engines.

    Reuses a cached SERP analysis (or computes + caches one) when the caller
    didn't already supply `serp_analysis`, so scoring doesn't re-scrape. The
    analysis is optional (per the Score-My-Page contract): if it can't be
    computed, scoring proceeds and nlp's deterministic engine falls back to a
    neutral baseline."""
    client = _get_client(client_id)
    fields = _business_fields(client)
    if not page_url and not page_content:
        raise HTTPException(status_code=400, detail="page_url_or_content_required")
    location, location_code = await locations_service.resolve_location(client, location, location_code)
    if not serp_analysis:
        serp_analysis = await _get_or_compute_analysis(
            keyword, location, location_code, force_refresh, user_id, required=False
        )
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
        "brand_voice": client.get("brand_voice"),
        "detected_icp": client.get("detected_icp"),
        "differentiators": client.get("differentiators") or [],
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


async def publish_page(page_id: str, user_id: str) -> dict:
    """Publish a saved Local SEO page to a Google Doc in the client's Drive folder
    via the Apps Script webhook (same path as the blog writer). The page's HTML is
    converted to Markdown (the webhook's expected `content` format), and the Doc
    id/url are persisted on the row."""
    if not settings.google_apps_script_url:
        raise HTTPException(status_code=503, detail="publish_not_configured")

    supabase = get_supabase()
    page = get_page(page_id)  # 404s if missing

    client_res = (
        supabase.table("clients")
        .select("name, google_drive_folder_id")
        .eq("id", page["client_id"])
        .single()
        .execute()
    )
    if not client_res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    folder_id = client_res.data.get("google_drive_folder_id")
    if not folder_id:
        raise HTTPException(status_code=422, detail="missing_google_drive_folder_id")

    markdown = html_to_markdown(page.get("content_html") or "")
    if not markdown.strip():
        raise HTTPException(status_code=422, detail="page_is_empty")

    title = page.get("page_title") or f"{page.get('keyword', '')} — {client_res.data['name']}"
    body = {"folder_id": folder_id, "title": title, "content": markdown}

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
            response = await http.post(settings.google_apps_script_url, json=body)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("local_seo.apps_script_http_error",
                     extra={"status": exc.response.status_code, "body": exc.response.text[:300]})
        raise HTTPException(status_code=502, detail="apps_script_http_error") from exc
    except Exception as exc:
        logger.error("local_seo.apps_script_call_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="apps_script_call_failed") from exc

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=f"apps_script_returned_error: {result.get('error', 'unknown')}")

    doc_id, doc_url = result.get("doc_id"), result.get("doc_url")
    supabase.table("local_seo_pages").update({
        "published_doc_id": doc_id,
        "published_doc_url": doc_url,
        "published_at": "now()",
    }).eq("id", page_id).execute()
    logger.info("local_seo.page_published", extra={"page_id": page_id, "doc_id": doc_id, "user_id": user_id})

    return {"success": True, "doc_id": doc_id, "doc_url": doc_url}
