"""Ecommerce Product & Collection Writer + Reoptimizer — platform-api service.

The sibling of `local_seo_service` for ecommerce pages (product descriptions +
collection/category pages). It proxies the private nlp-api's ecommerce endpoints
(`/generate-ecommerce-page`, `/score-ecommerce-page`, `/reoptimize-ecommerce-page`),
persists to `ecommerce_pages` / `ecommerce_page_scores`, and drives the same
`async_jobs` background-job spine (generate / reoptimize-by-URL / interactive
actions) as the Local SEO module.

Unlike Local SEO this module is national (no geo/location, no GBP payload, no
page templates). Competitor SERP analysis runs INSIDE the nlp endpoints (which
default `run_analysis=True`); the reoptimize-by-URL flow threads the analysis the
score call already produced into the rewrite so the SERP is scraped once, not
twice. Product facts come from a pasted `product_input` and/or a scraped
`source_url`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services.gbp_service import normalize_website_url
from services.google_docs import resolve_drive_folder
from services.wordpress_publish import WordPressPublishError, publish_to_wordpress

logger = logging.getLogger(__name__)

# Generation/reoptimization can take minutes (SERP scrape + Claude + scoring).
_GENERATE_TIMEOUT = 600
# Plain JSON endpoints (score) are faster but still scrape/score — headroom.
_JSON_TIMEOUT = 300

# Pages scoring at/above this are already strong enough that a rewrite isn't
# worth the cost — the batch reoptimizer skips them with a note. Overridable
# per request via `score_threshold`.
REOPT_SCORE_THRESHOLD = 75.0

_PAGE_TYPES = ("product", "collection")


def _norm_page_type(page_type: Optional[str]) -> str:
    return "collection" if (page_type or "").lower() == "collection" else "product"


# ── client helpers ───────────────────────────────────────────────────────────

def _get_client(client_id: str) -> dict:
    supabase = get_supabase()
    res = supabase.table("clients").select("*").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data


def _business_name(client: dict) -> str:
    gbp = client.get("gbp") or {}
    return gbp.get("business_name") or client.get("name") or ""


def _website(client: dict) -> Optional[str]:
    gbp = client.get("gbp") or {}
    return normalize_website_url(gbp.get("website") or client.get("website_url"))


def _brand_context(client: dict) -> str:
    """A short brand/category context string for the ecommerce scorer."""
    bits = [_business_name(client)]
    gbp = client.get("gbp") or {}
    category = gbp.get("gbp_category")
    if category:
        bits.append(str(category))
    return " — ".join(b for b in bits if b)


def _generate_payload(
    client: dict, keyword: str, page_type: str,
    source_url: Optional[str], product_input: Optional[str],
    page_template_url: Optional[str] = None, notes: Optional[str] = None,
) -> dict:
    """Map a suite client row to the nlp GenerateEcommerceRequest. The converged
    brand_voice / detected_icp / differentiators assets are passed through so the
    writer targets the client's voice + customers. `page_template_url` (products
    only) is the house PDP structure the writer mirrors. `notes` is high-priority
    per-job editorial guidance the writer follows."""
    return {
        "keyword": keyword,
        "page_type": page_type,
        "business_name": _business_name(client),
        "website": _website(client),
        "source_url": (source_url or "").strip() or None,
        "product_input": (product_input or "").strip() or None,
        "brand_voice": client.get("brand_voice"),
        "detected_icp": client.get("detected_icp"),
        "differentiators": client.get("differentiators") or [],
        "page_template_url": (page_template_url or "").strip() or None,
        "notes": (notes or "").strip() or None,
        "run_analysis": True,
    }


# ── nlp transport ────────────────────────────────────────────────────────────

async def _post_nlp(path: str, payload: dict, user_id: Optional[str] = None) -> dict:
    """POST to a plain-JSON nlp endpoint and return the parsed body. A 4xx from
    nlp is surfaced to the user (client-actionable); a 5xx/transport error maps
    to a generic provider error."""
    url = f"{settings.nlp_api_url}{path}"
    headers = {"X-User-ID": user_id} if user_id else None
    try:
        async with httpx.AsyncClient(timeout=_JSON_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                logger.warning(
                    "ecommerce.nlp_http_error",
                    extra={"path": path, "status_code": response.status_code, "body": response.text[:500]},
                )
                if 400 <= response.status_code < 500:
                    detail = "ecommerce_provider_error"
                    try:
                        body = response.json()
                        if isinstance(body, dict) and body.get("detail"):
                            detail = str(body["detail"])
                    except ValueError:
                        pass
                    raise HTTPException(status_code=response.status_code, detail=detail)
                raise HTTPException(status_code=502, detail="ecommerce_provider_error")
            try:
                return response.json()
            except ValueError as exc:
                logger.warning("ecommerce.nlp_decode_error", extra={"path": path, "body": response.text[:500]})
                raise HTTPException(status_code=502, detail="ecommerce_provider_error") from exc
    except httpx.HTTPError as exc:
        logger.warning("ecommerce.nlp_request_error", extra={"path": path, "error": str(exc)})
        raise HTTPException(status_code=502, detail="ecommerce_provider_error") from exc


async def _stream_nlp(path: str, payload: dict) -> dict:
    """POST to an SSE nlp endpoint and return the final `result` dict."""
    url = f"{settings.nlp_api_url}{path}"
    result: Optional[dict] = None
    try:
        async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.warning(
                        "ecommerce.stream_http_error",
                        extra={"path": path, "status_code": response.status_code, "body": body[:500]},
                    )
                    raise HTTPException(status_code=502, detail="ecommerce_provider_error")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        import json as _json
                        event = _json.loads(line[len("data:"):].strip())
                    except ValueError:
                        continue
                    step = event.get("step")
                    if step == "error":
                        logger.warning("ecommerce.stream_worker_error", extra={"path": path, "error": event.get("message")})
                        raise HTTPException(status_code=502, detail="ecommerce_generation_failed")
                    if step == "done":
                        result = event.get("result")
    except httpx.HTTPError as exc:
        logger.warning("ecommerce.stream_request_error", extra={"path": path, "error": str(exc)})
        raise HTTPException(status_code=502, detail="ecommerce_provider_error") from exc

    if not result:
        raise HTTPException(status_code=502, detail="ecommerce_no_result")
    return result


# ── persistence ──────────────────────────────────────────────────────────────

def _persist_page(
    client_id: str, keyword: str, page_type: str, source_url: Optional[str],
    product_input: Optional[str], mode: str, result: dict, user_id: str,
    notes: Optional[str] = None,
) -> dict:
    row = {
        "client_id": client_id,
        "keyword": keyword,
        "page_type": page_type,
        "source_url": (source_url or "").strip() or None,
        "product_input": (product_input or "").strip() or None,
        "notes": (notes or "").strip() or None,
        "content_html": result.get("content_html") or "",
        "schema_json": result.get("schema_json") or "",
        "page_title": result.get("page_title"),
        "content_gaps": result.get("content_gaps") or [],
        "researched_facts": result.get("researched_facts") or [],
        "composite_score": result.get("composite_score"),
        "composite_status": result.get("composite_status"),
        "engine_scores": result.get("engine_scores"),
        "mode": mode,
        "token_usage": result.get("token_usage"),
        "cost_breakdown": result.get("cost_breakdown"),
        "created_by": user_id,
    }
    insert = get_supabase().table("ecommerce_pages").insert(row).execute()
    page = insert.data[0]
    logger.info("ecommerce.page_persisted", extra={"client_id": client_id, "page_id": page["id"], "mode": mode})
    _record_score_run(client_id, keyword, page_type, mode, result, page_id=page["id"], page_url=None, user_id=user_id)
    return page


def _score_run_row(
    client_id: str, keyword: str, page_type: Optional[str], mode: str, result: dict,
    *, page_id: Optional[str], page_url: Optional[str], user_id: Optional[str],
) -> dict:
    """Build an `ecommerce_page_scores` row (pure — unit-testable)."""
    return {
        "client_id": client_id,
        "page_id": page_id,
        "keyword": keyword,
        "page_type": page_type,
        "page_url": page_url,
        "mode": mode,
        "composite_score": result.get("composite_score"),
        "composite_status": result.get("composite_status"),
        "engine_scores": result.get("engine_scores"),
        "deficiencies": result.get("deficiencies") or result.get("content_gaps") or [],
        "token_usage": result.get("token_usage"),
        "created_by": user_id,
    }


def _record_score_run(
    client_id: str, keyword: str, page_type: Optional[str], mode: str, result: dict,
    *, page_id: Optional[str] = None, page_url: Optional[str] = None, user_id: Optional[str] = None,
) -> None:
    """Insert one score-history row. Best-effort — never breaks the run."""
    if result.get("engine_scores") is None and result.get("composite_score") is None:
        return
    try:
        row = _score_run_row(client_id, keyword, page_type, mode, result, page_id=page_id, page_url=page_url, user_id=user_id)
        get_supabase().table("ecommerce_page_scores").insert(row).execute()
    except Exception:  # noqa: BLE001 — history logging must never break the run
        logger.warning("ecommerce.score_run_record_failed", extra={"client_id": client_id, "mode": mode, "page_id": page_id})


# ── core operations ──────────────────────────────────────────────────────────

async def generate_page(
    client_id: str, keyword: str, page_type: str,
    source_url: Optional[str], product_input: Optional[str], user_id: str,
    page_template_url: Optional[str] = None, notes: Optional[str] = None,
) -> dict:
    """Generate an ecommerce page for a client and persist it. Competitor SERP
    analysis runs inside the nlp endpoint (run_analysis defaults True).

    House PDP template (products only): the per-call `page_template_url` wins,
    else the client's saved default (`clients.ecommerce_page_template_url`), so
    every product follows the client's fixed house structure. Collections ignore
    it (they keep the default structure)."""
    client = _get_client(client_id)
    page_type = _norm_page_type(page_type)
    template_url = None
    if page_type == "product":
        template_url = (page_template_url or "").strip() or client.get("ecommerce_page_template_url")
    payload = _generate_payload(
        client, keyword.strip(), page_type, source_url, product_input,
        page_template_url=template_url, notes=notes,
    )
    result = await _stream_nlp("/generate-ecommerce-page", payload)
    return _persist_page(client_id, keyword.strip(), page_type, source_url, product_input, "generate", result, user_id, notes=notes)


async def score_page(
    client_id: str, keyword: str, page_type: str,
    page_url: Optional[str], page_content: Optional[str], user_id: Optional[str] = None,
    serp_analysis: Optional[dict] = None,
) -> dict:
    """Score an existing ecommerce page (by URL or raw HTML) against the 8
    engines. The nlp endpoint runs SERP analysis inline when none is supplied and
    returns it so the caller can reuse it."""
    client = _get_client(client_id)
    page_type = _norm_page_type(page_type)
    if not page_url and not page_content:
        raise HTTPException(status_code=400, detail="page_url_or_content_required")
    result = await _post_nlp("/score-ecommerce-page", {
        "keyword": keyword,
        "page_type": page_type,
        "page_url": page_url,
        "page_content": page_content,
        "business_name": _business_name(client),
        "brand_context": _brand_context(client),
        "serp_analysis": serp_analysis,
    }, user_id=user_id)
    _record_score_run(client_id, keyword, page_type, "score", result, page_id=None, page_url=page_url, user_id=user_id)
    return result


async def reoptimize_from(
    client_id: str, keyword: str, page_type: str,
    existing_page_html: Optional[str], existing_page_url: Optional[str],
    deficiencies: list[dict], serp_analysis: Optional[dict],
    product_input: Optional[str], user_id: str, notes: Optional[str] = None,
    score_threshold: float = REOPT_SCORE_THRESHOLD,
) -> dict:
    """Rewrite an existing ecommerce page to lift its score, then persist it as a
    `mode='reoptimize'` row. The nlp endpoint re-scores the rewrite and runs an
    auto-retry loop (keep-best) toward `score_threshold`. `notes` is high-priority
    editorial guidance (e.g. drop a designation) the rewrite follows."""
    client = _get_client(client_id)
    page_type = _norm_page_type(page_type)
    if not existing_page_html and not existing_page_url:
        raise HTTPException(status_code=400, detail="page_url_or_html_required")
    result = await _stream_nlp("/reoptimize-ecommerce-page", {
        "keyword": keyword,
        "page_type": page_type,
        "existing_page_html": existing_page_html,
        "existing_page_url": existing_page_url,
        "deficiencies": deficiencies or [],
        "business_name": _business_name(client),
        "brand_voice": client.get("brand_voice"),
        "detected_icp": client.get("detected_icp"),
        "serp_analysis": serp_analysis,
        "product_input": (product_input or "").strip() or None,
        "notes": (notes or "").strip() or None,
        "score_threshold": score_threshold,
    })
    return _persist_page(client_id, keyword, page_type, existing_page_url, product_input, "reoptimize", result, user_id, notes=notes)


async def reoptimize_url(
    client_id: str, page_url: str, keyword: str, page_type: str, user_id: str,
    score_threshold: float = REOPT_SCORE_THRESHOLD, publish_to_doc: bool = False,
    notes: Optional[str] = None,
) -> dict:
    """Score a live page (by URL) and reoptimize it only if it scores below
    `score_threshold`. The SERP analysis the score produced is threaded into the
    rewrite so the SERP is scraped once. Returns a status dict (skipped |
    reoptimized), mirroring the Local SEO reoptimize-by-URL contract.

    When `notes` are supplied the score-threshold skip is BYPASSED — the notes are
    an explicit rewrite instruction (e.g. "remove the Research Use Only
    designation") that must apply even to an already-high-scoring page."""
    page_type = _norm_page_type(page_type)
    score_result = await score_page(
        client_id, keyword, page_type, page_url=page_url, page_content=None, user_id=user_id,
    )
    # Record the "before" verdict distinctly (score_page already logged a 'score'
    # row; re-tag as reoptimize_before for the reoptimize history semantics).
    _record_score_run(client_id, keyword, page_type, "reoptimize_before", score_result, page_id=None, page_url=page_url, user_id=user_id)

    composite = score_result.get("composite_score")
    if composite is not None and composite >= score_threshold and not (notes or "").strip():
        logger.info("ecommerce.reoptimize_url_skipped", extra={"client_id": client_id, "page_url": page_url, "score": composite})
        return {
            "status": "skipped",
            "page_url": page_url,
            "keyword": keyword,
            "score": composite,
            "threshold": score_threshold,
            "reason": (
                f"Already scores {round(composite)}/100 — at or above the "
                f"{int(score_threshold)} threshold, so reoptimization was skipped."
            ),
        }

    page = await reoptimize_from(
        client_id=client_id, keyword=keyword, page_type=page_type,
        existing_page_html=None, existing_page_url=page_url,
        deficiencies=score_result.get("deficiencies") or [],
        serp_analysis=score_result.get("serp_analysis"),
        product_input=None, user_id=user_id, notes=notes,
        score_threshold=score_threshold,
    )

    out: dict = {
        "status": "reoptimized",
        "page_url": page_url,
        "keyword": keyword,
        "prev_score": composite,
        "new_score": page.get("composite_score"),
        "page": {
            "id": page["id"],
            "page_title": page.get("page_title"),
            "composite_score": page.get("composite_score"),
            "composite_status": page.get("composite_status"),
            "published_doc_url": page.get("published_doc_url"),
        },
    }
    if publish_to_doc:
        try:
            pub = await publish_page(page["id"], user_id)
            out["published"] = {"doc_url": pub.get("doc_url"), "doc_id": pub.get("doc_id")}
            out["page"]["published_doc_url"] = pub.get("doc_url")
        except Exception as exc:
            out["publish_error"] = str(getattr(exc, "detail", None) or exc or "publish_failed")
            logger.warning("ecommerce.reoptimize_url_publish_failed", extra={"client_id": client_id, "page_id": page["id"], "error": str(exc)})
    return out


# ── CRUD / lifecycle ─────────────────────────────────────────────────────────

_LIST_COLUMNS = (
    "id, client_id, keyword, page_type, source_url, page_title, composite_score, "
    "composite_status, mode, created_at, deleted_at, "
    "published_doc_url, published_url, published_at"
)


def list_pages(client_id: str, deleted: bool = False) -> list[dict]:
    """List a client's ecommerce pages. ``deleted=False`` → Saved; ``True`` → Drafts."""
    supabase = get_supabase()
    query = supabase.table("ecommerce_pages").select(_LIST_COLUMNS).eq("client_id", client_id)
    if deleted:
        query = query.not_.is_("deleted_at", "null").order("deleted_at", desc=True)
    else:
        query = query.is_("deleted_at", "null").order("created_at", desc=True)
    return query.execute().data or []


def get_page(page_id: str) -> dict:
    res = get_supabase().table("ecommerce_pages").select("*").eq("id", page_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="ecommerce_page_not_found")
    return res.data


def list_score_history(client_id: str, page_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    limit = max(1, min(limit, 500))
    supabase = get_supabase()
    query = supabase.table("ecommerce_page_scores").select("*").eq("client_id", client_id)
    if page_id:
        query = query.eq("page_id", page_id)
    return query.order("created_at", desc=True).limit(limit).execute().data or []


def delete_page(page_id: str) -> None:
    """Soft-delete: move the page to Drafts (set deleted_at)."""
    supabase = get_supabase()
    res = (
        supabase.table("ecommerce_pages").update({"deleted_at": "now()"})
        .eq("id", page_id).is_("deleted_at", "null").execute()
    )
    if not res.data:
        existing = supabase.table("ecommerce_pages").select("id").eq("id", page_id).execute().data
        if not existing:
            raise HTTPException(status_code=404, detail="ecommerce_page_not_found")
    logger.info("ecommerce.page_drafted", extra={"page_id": page_id})


def restore_page(page_id: str) -> dict:
    res = get_supabase().table("ecommerce_pages").update({"deleted_at": None}).eq("id", page_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="ecommerce_page_not_found")
    logger.info("ecommerce.page_restored", extra={"page_id": page_id})
    return res.data[0]


def purge_page(page_id: str) -> None:
    res = get_supabase().table("ecommerce_pages").delete().eq("id", page_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="ecommerce_page_not_found")
    logger.info("ecommerce.page_purged", extra={"page_id": page_id})


def purge_drafts(client_id: str) -> int:
    res = (
        get_supabase().table("ecommerce_pages").delete()
        .eq("client_id", client_id).not_.is_("deleted_at", "null").execute()
    )
    count = len(res.data or [])
    logger.info("ecommerce.drafts_purged", extra={"client_id": client_id, "count": count})
    return count


def set_featured_image(page_id: str, url: Optional[str]) -> dict:
    res = get_supabase().table("ecommerce_pages").update({"featured_image_url": url or None}).eq("id", page_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="ecommerce_page_not_found")
    return {"featured_image_url": url or None}


# ── house PDP template (products only) ───────────────────────────────────────

def get_page_template_default(client_id: str) -> dict:
    """Return the client's saved house PDP template URL (products mirror it)."""
    res = get_supabase().table("clients").select("ecommerce_page_template_url").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return {"ecommerce_page_template_url": res.data.get("ecommerce_page_template_url")}


def set_page_template_default(client_id: str, page_template_url: Optional[str]) -> dict:
    """Persist (or clear, when falsy) the client's house PDP template URL. Applied
    to every PRODUCT generation so all product descriptions follow one structure."""
    url = (page_template_url or "").strip() or None
    res = (
        get_supabase().table("clients")
        .update({"ecommerce_page_template_url": url, "updated_at": "now()"})
        .eq("id", client_id).execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    logger.info("ecommerce.page_template_default_set", extra={"client_id": client_id, "set": bool(url)})
    return {"ecommerce_page_template_url": url}


# ── publish ──────────────────────────────────────────────────────────────────

async def _publish_page_to_wordpress(page: dict, client: dict, user_id: str, status: str) -> dict:
    title = page.get("page_title") or f"{page.get('keyword', '')} — {client.get('name', '')}"
    html = page.get("content_html") or ""
    try:
        result = await publish_to_wordpress(
            client=client, title=title, html=html, status=status,
            content_type="ecommerce_page", featured_image_url=page.get("featured_image_url"),
        )
    except WordPressPublishError as exc:
        client_errors = {
            "wordpress_not_configured", "invalid_wordpress_site_url",
            "wordpress_site_url_must_be_https", "invalid_status", "content_is_empty",
        }
        code = 422 if str(exc) in client_errors else 502
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    get_supabase().table("ecommerce_pages").update({
        "published_url": result.get("link"), "published_at": "now()",
    }).eq("id", page["id"]).execute()
    logger.info("ecommerce.page_published_wordpress", extra={"page_id": page["id"], "post_id": result.get("post_id"), "user_id": user_id})
    return {
        "success": True, "destination": "wordpress", "post_id": result.get("post_id"),
        "url": result.get("link"), "edit_url": result.get("edit_link"), "status": result.get("status"),
    }


async def publish_page(
    page_id: str, user_id: str, destination: str = "google_docs", status: str = "draft",
) -> dict:
    """Publish a saved ecommerce page to a Google Doc in the client's Drive folder
    (default) or to the client's WordPress site (destination='wordpress'). The
    publish target is persisted on the row."""
    if destination == "google_docs" and not settings.google_apps_script_url:
        raise HTTPException(status_code=503, detail="publish_not_configured")

    supabase = get_supabase()
    page = get_page(page_id)

    if destination == "wordpress":
        client_res = (
            supabase.table("clients")
            .select("name, wordpress_site_url, wordpress_username, wordpress_app_password")
            .eq("id", page["client_id"]).single().execute()
        )
        if not client_res.data:
            raise HTTPException(status_code=404, detail="client_not_found")
        return await _publish_page_to_wordpress(page, client_res.data, user_id, status)

    client_res = (
        supabase.table("clients").select("name, google_drive_folder_id, drive_folders")
        .eq("id", page["client_id"]).single().execute()
    )
    if not client_res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    folder_id = resolve_drive_folder(client_res.data, "ecommerce_page")
    if not folder_id:
        raise HTTPException(status_code=422, detail="missing_google_drive_folder_id")

    content_html = page.get("content_html") or ""
    if not content_html.strip():
        raise HTTPException(status_code=422, detail="page_is_empty")
    featured = page.get("featured_image_url")
    if featured:
        content_html = f'<p><img src="{featured}" /></p>\n{content_html}'
    title = page.get("page_title") or f"{page.get('keyword', '')} — {client_res.data['name']}"
    body = {"folder_id": folder_id, "title": title, "content": content_html, "format": "html"}

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
            response = await http.post(settings.google_apps_script_url, json=body)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("ecommerce.apps_script_http_error", extra={"status": exc.response.status_code, "body": exc.response.text[:300]})
        raise HTTPException(status_code=502, detail="apps_script_http_error") from exc
    except Exception as exc:
        logger.error("ecommerce.apps_script_call_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="apps_script_call_failed") from exc

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=f"apps_script_returned_error: {result.get('error', 'unknown')}")

    doc_id, doc_url = result.get("doc_id"), result.get("doc_url")
    supabase.table("ecommerce_pages").update({
        "published_doc_id": doc_id, "published_doc_url": doc_url, "published_at": "now()",
    }).eq("id", page_id).execute()
    logger.info("ecommerce.page_published", extra={"page_id": page_id, "doc_id": doc_id, "user_id": user_id})
    return {"success": True, "doc_id": doc_id, "doc_url": doc_url}


# ── background jobs (per-item async jobs — same rationale as Local SEO) ───────

def _bulk_scheduled_at(index: int) -> str:
    """Staggered `scheduled_at` so bulk runs at background priority (reuses the
    Local SEO spacing setting)."""
    spacing = settings.local_seo_bulk_job_spacing_seconds
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


async def enqueue_generate(
    client_id: str, keyword: str, page_type: str,
    source_url: Optional[str], product_input: Optional[str], user_id: str,
    page_template_url: Optional[str] = None, notes: Optional[str] = None,
) -> str:
    """Enqueue an `ecommerce_generate` job. Returns the job id. `page_template_url`
    is an optional per-call override of the client's house PDP template (products
    only); when omitted, generate_page falls back to the client's saved default.
    `notes` is per-job writing guidance the writer follows."""
    _get_client(client_id)
    res = get_supabase().table("async_jobs").insert({
        "job_type": "ecommerce_generate",
        "entity_id": client_id,
        "payload": {
            "client_id": client_id,
            "keyword": keyword.strip(),
            "page_type": _norm_page_type(page_type),
            "source_url": (source_url or "").strip() or None,
            "product_input": (product_input or "").strip() or None,
            "page_template_url": (page_template_url or "").strip() or None,
            "notes": (notes or "").strip() or None,
            "user_id": user_id,
        },
    }).execute()
    return res.data[0]["id"]


async def run_generate_job(job: dict) -> None:
    payload = job.get("payload") or {}
    job_id = job["id"]
    supabase = get_supabase()
    try:
        page = await generate_page(
            client_id=payload["client_id"], keyword=payload["keyword"],
            page_type=payload.get("page_type", "product"),
            source_url=payload.get("source_url"), product_input=payload.get("product_input"),
            user_id=payload["user_id"], page_template_url=payload.get("page_template_url"),
            notes=payload.get("notes"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"page_id": page["id"]}, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("ecommerce.generate_job_complete", extra={"job_id": job_id, "page_id": page["id"]})
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("ecommerce.generate_job_failed", extra={"job_id": job_id, "error": str(detail)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def get_generate_job(job_id: str, client_id: str) -> dict:
    res = (
        get_supabase().table("async_jobs").select("status, result, error, entity_id")
        .eq("id", job_id).limit(1).execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="generate_job_not_found")
    row = res.data[0]
    result = row.get("result") or {}
    return {"status": row["status"], "page_id": result.get("page_id"), "error": row.get("error")}


async def enqueue_generate_bulk(
    client_id: str, keywords: list[str], page_type: str, user_id: str,
    notes: Optional[str] = None,
) -> list[str]:
    """Enqueue one `ecommerce_generate` job per keyword. Returns job ids. `notes`
    is batch-level writing guidance applied to every page in the batch."""
    _get_client(client_id)
    ptype = _norm_page_type(page_type)
    note = (notes or "").strip() or None
    rows = []
    for kw in keywords:
        if not (kw or "").strip():
            continue
        rows.append({
            "job_type": "ecommerce_generate",
            "entity_id": client_id,
            "scheduled_at": _bulk_scheduled_at(len(rows)),
            "payload": {
                "client_id": client_id, "keyword": kw.strip(), "page_type": ptype,
                "source_url": None, "product_input": None, "notes": note, "user_id": user_id,
            },
        })
    if not rows:
        return []
    res = get_supabase().table("async_jobs").insert(rows).execute()
    return [r["id"] for r in (res.data or [])]


async def enqueue_reoptimize_bulk(
    client_id: str, targets: list[dict], user_id: str,
    score_threshold: Optional[float] = None, publish_to_doc: bool = False,
    notes: Optional[str] = None,
) -> list[dict]:
    """Enqueue one `ecommerce_reoptimize_url` job per target. Each target is
    ``{page_url, keyword, page_type}``. Returns ``[{job_id, page_url}]``. `notes`
    is batch-level guidance applied to every rewrite (and forces the rewrite even
    on an already-high-scoring page)."""
    _get_client(client_id)
    threshold = REOPT_SCORE_THRESHOLD if score_threshold is None else score_threshold
    note = (notes or "").strip() or None
    rows = []
    for t in targets:
        page_url = (t.get("page_url") or "").strip()
        if not page_url:
            continue
        rows.append({
            "job_type": "ecommerce_reoptimize_url",
            "entity_id": client_id,
            "scheduled_at": _bulk_scheduled_at(len(rows)),
            "payload": {
                "client_id": client_id, "page_url": page_url,
                "keyword": (t.get("keyword") or "").strip(),
                "page_type": _norm_page_type(t.get("page_type")),
                "user_id": user_id, "score_threshold": threshold,
                "publish_to_doc": bool(publish_to_doc), "notes": note,
            },
        })
    if not rows:
        return []
    res = get_supabase().table("async_jobs").insert(rows).execute()
    return [{"job_id": r["id"], "page_url": rows[i]["payload"]["page_url"]} for i, r in enumerate(res.data or [])]


async def run_reoptimize_url_job(job: dict) -> None:
    payload = job.get("payload") or {}
    job_id = job["id"]
    supabase = get_supabase()
    try:
        result = await reoptimize_url(
            client_id=payload["client_id"], page_url=payload["page_url"],
            keyword=payload["keyword"], page_type=payload.get("page_type", "product"),
            user_id=payload["user_id"], score_threshold=payload.get("score_threshold", REOPT_SCORE_THRESHOLD),
            publish_to_doc=bool(payload.get("publish_to_doc")), notes=payload.get("notes"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("ecommerce.reoptimize_job_complete", extra={"job_id": job_id})
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("ecommerce.reoptimize_job_failed", extra={"job_id": job_id, "error": str(detail)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def get_jobs_status(client_id: str, job_ids: list[str]) -> list[dict]:
    if not job_ids:
        return []
    res = (
        get_supabase().table("async_jobs").select("id, status, result, error, entity_id")
        .in_("id", job_ids).execute()
    )
    out = []
    for row in res.data or []:
        if row.get("entity_id") != client_id:
            continue
        out.append({"job_id": row["id"], "status": row["status"], "result": row.get("result"), "error": row.get("error")})
    return out


_JOB_TYPES = ("ecommerce_generate", "ecommerce_reoptimize_url", "ecommerce_action")


def cancel_queued_jobs(client_id: str, job_ids: Optional[list[str]] = None) -> dict:
    """Cancel QUEUED (pending) ecommerce jobs for a client so they never run.

    The worker only ever claims jobs with status='pending', so flipping them to a
    terminal state removes them from the queue. async_jobs has no 'cancelled'
    status (CHECK allows pending/running/complete/failed), so we mark them
    'failed' with a `cancelled_by_user` marker. A job already 'running' cannot be
    interrupted mid-flight and is intentionally left to finish. Optionally scope
    to specific `job_ids`; otherwise cancels ALL of the client's pending ecommerce
    jobs. Returns ``{"cancelled": N}``."""
    query = (
        get_supabase().table("async_jobs")
        .update({"status": "failed", "error": "cancelled_by_user", "completed_at": "now()"})
        .eq("entity_id", client_id)
        .eq("status", "pending")
        .in_("job_type", list(_JOB_TYPES))
    )
    if job_ids:
        query = query.in_("id", job_ids)
    res = query.execute()
    count = len(res.data or [])
    logger.info("ecommerce.jobs_cancelled", extra={"client_id": client_id, "count": count})
    return {"cancelled": count}


# ── interactive actions (score / discover) as backgrounded jobs ──────────────

_ACTION_JOB_TYPE = "ecommerce_action"


async def enqueue_action(client_id: str, action: str, args: dict, user_id: str) -> str:
    """Enqueue an `ecommerce_action` job (score | discover). Returns the job id."""
    _get_client(client_id)
    res = get_supabase().table("async_jobs").insert({
        "job_type": _ACTION_JOB_TYPE,
        "entity_id": client_id,
        "payload": {"client_id": client_id, "action": action, "args": args or {}, "user_id": user_id},
    }).execute()
    return res.data[0]["id"]


async def _run_action(action: str, client_id: str, args: dict, user_id: str) -> dict:
    if action == "score":
        return await score_page(
            client_id, args.get("keyword", ""), args.get("page_type", "product"),
            page_url=args.get("page_url"), page_content=args.get("page_content"), user_id=user_id,
        )
    if action == "discover":
        from services.ecommerce_discovery import discover_pages
        return await discover_pages(client_id, args.get("page_type"))
    raise HTTPException(status_code=400, detail="unknown_ecommerce_action")


async def run_ecommerce_action_job(job: dict) -> None:
    payload = job.get("payload") or {}
    job_id = job["id"]
    supabase = get_supabase()
    try:
        result = await _run_action(
            payload.get("action", ""), payload["client_id"], payload.get("args") or {}, payload["user_id"],
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("ecommerce.action_job_failed", extra={"job_id": job_id, "error": str(detail)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
