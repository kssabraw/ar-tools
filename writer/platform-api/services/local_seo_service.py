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
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx
from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import analysis_cache, locations_service, page_spec, page_spec_store
from services.gbp_service import normalize_website_url
from services.google_docs import resolve_drive_folder
from services.wordpress_publish import WordPressPublishError, publish_to_wordpress

logger = logging.getLogger(__name__)

# Generation/reoptimization can take minutes (SERP scrape + Claude + scoring).
_GENERATE_TIMEOUT = 600
# Hard stop for a single /generate-page attempt: if nlp hasn't returned within
# this window the SSE connection is severed and the attempt fails. Paired with
# the nlp GENERATION_TIME_BUDGET_SECONDS soft cap (which stops starting new
# rewrite/rescore passes earlier) — the soft cap ships the best page, this is the
# backstop. Kept separate from _GENERATE_TIMEOUT so it does NOT shorten the
# reoptimize-page flow (which has its own multi-pass loop and no time budget).
# 8 min: wide enough that a pass started just under the 4-min soft budget always
# finishes and ships, rather than being severed mid-rewrite at the hard stop.
_GENERATE_PAGE_TIMEOUT = 480
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
        # Repair/clean the stored URL defensively — historic rows may carry a
        # GBP tracking link whose query was percent-encoded into the path
        # (`…/page/%3Futm_source%3D…`), which 404s and breaks every downstream
        # scrape/probe (brand voice, page generation, …).
        "website": normalize_website_url(gbp.get("website") or client.get("website_url")),
    }


def _gbp_to_generate_payload(
    client: dict, keyword: str, location: str, location_code: Optional[int] = None,
    include_decision_map: bool = True, entity_provider: Optional[str] = None,
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
        # Analysis always runs first; nlp only skips it if we degrade below.
        "run_analysis": True,
        # Decision-fit "which is right for you" block is on by default (every
        # local page); callers can suppress it for a purely transactional page.
        "include_decision_map": include_decision_map,
        "brand_voice": client.get("brand_voice"),
        "detected_icp": client.get("detected_icp"),
        "differentiators": client.get("differentiators") or [],
        # Per-request entity-extraction provider ("textrazor"|"google"); None →
        # nlp's default. Threaded from the UI so the SERP entity analysis inside
        # nlp uses the chosen engine.
        "entity_provider": entity_provider,
    }


def _gbp_to_rankability_payload(
    client: dict, keyword: str, location: str, location_code: Optional[int], sab_city: Optional[str],
) -> dict:
    """Map a suite client row to the nlp service's RankabilityRequest, sourcing
    the business identity from the client's stored GBP record. The nlp service
    infers SAB-vs-physical from the address and uses lat/lng (physical) or the
    geocoded `sab_city` (SAB) for the distance check."""
    gbp = client.get("gbp") or {}
    fields = _business_fields(client)
    return {
        "keyword": keyword,
        "location": location,
        "location_code": location_code,
        "gbp_category": fields["gbp_category"],
        "business_name": fields["business_name"],
        "business_address": fields["address"],
        "business_review_count": gbp.get("gbp_review_count"),
        "business_lat": gbp.get("latitude"),
        "business_lng": gbp.get("longitude"),
        "website": fields["website"],
        "sab_city": (sab_city or "").strip() or None,
        "gbp_place_id": client.get("gbp_place_id"),
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
                # A 4xx from nlp is client-actionable — e.g. a 422 "Your website
                # returned a 404 error. Check that the URL is correct and the
                # site is live." Surface that message (and status) so the user
                # knows what to fix, instead of the opaque provider error. 5xx
                # stays a generic provider error (nothing the user can do).
                if 400 <= response.status_code < 500:
                    detail = "local_seo_provider_error"
                    try:
                        body = response.json()
                        if isinstance(body, dict) and body.get("detail"):
                            detail = str(body["detail"])
                    except ValueError:
                        pass
                    raise HTTPException(status_code=response.status_code, detail=detail)
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


async def _stream_nlp(
    path: str, payload: dict, timeout: float = _GENERATE_TIMEOUT,
    on_progress: Optional[Callable[[Optional[int], Optional[str]], Awaitable[None]]] = None,
) -> dict:
    """POST to an SSE nlp endpoint (`/generate-page`, `/reoptimize-page`) and
    return the final `result` dict. Raises HTTPException on provider error.
    `timeout` is the hard stop for the whole attempt (generate uses the tighter
    _GENERATE_PAGE_TIMEOUT; reoptimize keeps the longer default).

    `on_progress(percent, message)` — when supplied, called for each per-stage
    `progress` SSE event so a background job can surface live progress. Awaited
    but best-effort: a failing progress write never interrupts the stream."""
    url = f"{settings.nlp_api_url}{path}"
    result: Optional[dict] = None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    logger.warning(
                        "local_seo.stream_http_error",
                        extra={"path": path, "status_code": response.status_code, "body": body[:500]},
                    )
                    # Name the upstream status so a persisted failure distinguishes
                    # "nlp is down" (502/503) from "nlp rejected the request" (4xx).
                    raise HTTPException(
                        status_code=502,
                        detail=f"local_seo_provider_error: nlp returned HTTP {response.status_code}",
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[len("data:"):].strip())
                    except json.JSONDecodeError:
                        continue
                    # Valid JSON isn't necessarily an object: `data: null` parses
                    # fine and would crash the next line with "'NoneType' object
                    # has no attribute 'get'". Skip it like an unparseable line.
                    if not isinstance(event, dict):
                        continue
                    step = event.get("step")
                    if step == "progress" and on_progress is not None:
                        try:
                            await on_progress(event.get("progress"), event.get("message"))
                        except Exception:  # noqa: BLE001 — progress is best-effort
                            pass
                        continue
                    if step == "error":
                        # The nlp worker's own message says WHY generation failed.
                        # Logging it alone is not enough: for a background job the
                        # detail is what lands in `async_jobs.error`, and logs roll
                        # off — 65 `local_seo_generation_failed` rows are now
                        # permanently undiagnosable because the reason was dropped
                        # here. Keep the code as a prefix so matching still works.
                        message = str(event.get("message") or "").strip()
                        logger.warning(
                            "local_seo.stream_worker_error",
                            extra={"path": path, "error": message},
                        )
                        raise HTTPException(
                            status_code=502,
                            detail=(f"local_seo_generation_failed: {message[:400]}"
                                    if message else "local_seo_generation_failed"),
                        )
                    if step == "done":
                        result = event.get("result")
    except httpx.HTTPError as exc:
        logger.warning("local_seo.stream_request_error", extra={"path": path, "error": str(exc)})
        raise HTTPException(status_code=502, detail="local_seo_provider_error") from exc

    if not result:
        raise HTTPException(status_code=502, detail="local_seo_no_result")
    return result


def _job_progress_writer(job_id: Optional[str]):
    """Return an async callback that writes live progress (percent + stage
    message) onto the async_jobs row for `job_id`, so the frontend jobs/status
    poll can render a moving bar instead of a frozen one. Best-effort and guarded
    on status='running' (never touches a finished job); returns None when there's
    no job_id, so streaming stays a no-op off the background-job path."""
    if not job_id:
        return None

    async def _write(percent: Optional[int], message: Optional[str]) -> None:
        try:
            update: dict = {}
            if percent is not None:
                update["progress"] = max(0, min(100, int(percent)))
            if message:
                update["progress_message"] = str(message)[:200]
            if not update:
                return
            get_supabase().table("async_jobs").update(update).eq(
                "id", job_id
            ).eq("status", "running").execute()
        except Exception:  # noqa: BLE001 — best-effort, never break the job
            pass

    return _write


# ── persistence ─────────────────────────────────────────────────────────────

def _persist_page(client_id: str, keyword: str, location: str, run_analysis: bool, mode: str, result: dict, user_id: str, notes: Optional[str] = None) -> dict:
    row = {
        "client_id": client_id,
        "keyword": keyword,
        "location": location,
        "run_analysis": run_analysis,
        "notes": (notes or "").strip() or None,
        "content_html": result.get("content_html") or "",
        "schema_json": result.get("schema_json") or "",
        "page_title": result.get("page_title"),
        "content_gaps": result.get("content_gaps") or [],
        "composite_score": result.get("composite_score"),
        "composite_status": result.get("composite_status"),
        # Full per-engine verdict (nlp surfaces this on generate/reoptimize). None
        # on older nlp builds that don't emit it — the column is nullable.
        "engine_scores": result.get("engine_scores"),
        # Structural-fidelity verdict from the generation gate ({composite,
        # dimensions, notes}). None when no reference structure drove the page.
        "structure_fidelity": result.get("structure_fidelity"),
        # Brand-voice verdict: the full scorecard (headline score, band, the
        # eight per-dimension results, deterministic violations) as jsonb, with
        # the headline number lifted into its own column so it can be sorted and
        # filtered beside the SEO score. Both null when the client has no brand
        # guide on file — which is not the same as scoring zero.
        "voice_violations": result.get("voice_compliance"),
        "voice_score": (result.get("voice_compliance") or {}).get("score"),
        # The page spec this page was written against + how it landed
        # (attach_length_verdict). All null for pages generated without a spec.
        "page_spec_id": result.get("page_spec_id"),
        "spec_version": result.get("spec_version"),
        "target_words": result.get("target_words"),
        "actual_words": result.get("actual_words"),
        "length_status": result.get("length_status"),
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
    # Log the run's verdict to the score history (best-effort — never fail the run).
    _record_score_run(
        client_id, keyword, location, mode, result,
        page_id=page["id"], page_url=None, user_id=user_id,
    )
    return page


# ── score-run history ─────────────────────────────────────────────────────────
# Every scoring run (standalone score, generate, reoptimize before/after) logs its
# full verdict to `local_seo_page_scores` so the per-engine breakdown is kept, not
# just the composite. Writes are best-effort: a history-log failure must never
# break the actual generation/scoring the user asked for.

def _score_run_row(
    client_id: str, keyword: str, location: Optional[str], mode: str, result: dict,
    *, page_id: Optional[str], page_url: Optional[str], user_id: Optional[str],
) -> dict:
    """Build a `local_seo_page_scores` row from a score/generate/reoptimize result.
    Pure (no I/O) so it's unit-testable. `deficiencies` falls back to `content_gaps`
    for result shapes (generate) that carry the engine failures under that key."""
    return {
        "client_id": client_id,
        "page_id": page_id,
        "keyword": keyword,
        "location": location,
        "page_url": page_url,
        "mode": mode,
        "composite_score": result.get("composite_score"),
        "composite_status": result.get("composite_status"),
        "engine_scores": result.get("engine_scores"),
        "structure_fidelity": result.get("structure_fidelity"),
        "deficiencies": result.get("deficiencies") or result.get("content_gaps") or [],
        "token_usage": result.get("token_usage"),
        "created_by": user_id,
    }


def _record_score_run(
    client_id: str, keyword: str, location: Optional[str], mode: str, result: dict,
    *, page_id: Optional[str] = None, page_url: Optional[str] = None, user_id: Optional[str] = None,
) -> None:
    """Insert one score-history row. Best-effort: logs and swallows any failure so
    the surrounding generate/score/reoptimize operation is never lost to a history
    write. Skips silently when there's no verdict to record (no engine_scores and
    no composite)."""
    if result.get("engine_scores") is None and result.get("composite_score") is None:
        return
    try:
        row = _score_run_row(
            client_id, keyword, location, mode, result,
            page_id=page_id, page_url=page_url, user_id=user_id,
        )
        get_supabase().table("local_seo_page_scores").insert(row).execute()
    except Exception:  # noqa: BLE001 — history logging must never break the run
        logger.warning(
            "local_seo.score_run_record_failed",
            extra={"client_id": client_id, "mode": mode, "page_id": page_id},
        )


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
    entity_provider: Optional[str] = None,
) -> Optional[dict]:
    """Run the nlp SERP analysis and cache it. On provider failure: re-raise when
    `required` (the analysis IS the deliverable), else log and return None so the
    caller can degrade gracefully (generate/score are enhanced by analysis, not
    gated on it). `entity_provider` picks the nlp entity-extraction engine
    ("textrazor"|"google"); None → nlp's default."""
    try:
        result = await _post_nlp("/analyze", {
            "keyword": keyword,
            "location": location,
            "location_code": location_code,
            "entity_provider": entity_provider,
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


def fallback_word_target(targets: list[int], default: int) -> int:
    """Pure: the standing length target for a market when a keyword's own SERP
    analysis is unavailable — the median of the newest cached targets at the
    same location (robust to one unusually long/short SERP), else `default`.
    Never below 1."""
    clean = [int(t) for t in (targets or []) if isinstance(t, (int, float)) and t > 0]
    if not clean:
        return max(1, int(default))
    return max(1, int(round(statistics.median(clean))))


def _resolve_fallback_length_target(location_code: Optional[int], location: str) -> int:
    """Impure: the market's standing word target (see `fallback_word_target`)."""
    targets = analysis_cache.recent_word_targets(
        location_code, location, limit=settings.local_seo_fallback_target_samples
    )
    return fallback_word_target(targets, settings.local_seo_fallback_word_target)


def _notify_analysis_degraded(client_id: str, keyword: str, location: str, target: int) -> None:
    """Surface a generate that ran WITHOUT competitor analysis. Before this the
    degrade was invisible — the job completed, the page looked normal, and only
    the SERP-coverage engine's neutral 50 hinted anything was missing. One
    notification per client+keyword (a bulk batch must not fire N)."""
    try:
        from services import notifications  # lazy: keep this module's import graph small

        notifications.emit(
            client_id,
            kind="content_no_serp_analysis",
            title="Local SEO page written without competitor analysis",
            summary=(
                f"The competitor SERP analysis for '{keyword}' ({location}) could not be "
                f"run (provider unavailable), so the page was written from business data "
                f"alone with a fallback length target of ~{target} words. Its SERP-coverage "
                f"score is neutral. Once the provider is back, reoptimize the page from "
                f"Saved Pages to write it against the real competitor set."
            ),
            severity="warning",
            payload={"keyword": keyword, "location": location, "length_target": target},
            dedupe_key=f"content_no_serp_analysis:{client_id}:{keyword.strip().lower()}",
        )
    except Exception as exc:  # noqa: BLE001 — a notification failure never blocks generation
        logger.warning("local_seo.analysis_degraded_notify_failed", extra={"error": str(exc)})


async def _get_or_compute_analysis(
    keyword: str,
    location: str,
    location_code: Optional[int],
    force_refresh: bool,
    user_id: Optional[str] = None,
    required: bool = True,
    entity_provider: Optional[str] = None,
) -> Optional[dict]:
    """Return a SERP analysis for (keyword, location), served from the shared
    cache when fresh (within the TTL) — otherwise run the nlp pipeline once and
    cache the result. `force_refresh` bypasses the cache for a re-scrape;
    `required=False` degrades to None on provider failure instead of raising.
    `entity_provider` picks the nlp entity-extraction engine on a compute."""
    if force_refresh:
        return await _compute_and_store(
            keyword, location, location_code, user_id, required, entity_provider
        )

    cached = analysis_cache.get(keyword, location_code, location)
    if cached is not None:
        return cached
    # Miss → single-flight so concurrent identical requests don't all re-scrape.
    async with _analysis_lock(analysis_cache.cache_key(keyword, location_code, location)):
        cached = analysis_cache.get(keyword, location_code, location)
        if cached is not None:
            return cached
        return await _compute_and_store(
            keyword, location, location_code, user_id, required, entity_provider
        )


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


async def _apply_structure_gate(
    result: dict, payload: dict, reference_analysis: Optional[dict]
) -> dict:
    """Score the generated page's structural fidelity against the client's stored
    reference outline and, when it drifted on layout (wrong section count/order,
    dropped FAQ/CTA/table/list blocks), regenerate with the specific corrections
    fed back — keep-best by structural composite. Turns the reference structure
    from prompt guidance the model can ignore into a measured requirement. Runs
    only when a reference structure drove this generation; best-effort via the
    shared structure_gate helper."""
    from services import structure_gate

    async def _regenerate(corrections: str) -> Optional[dict]:
        return await _stream_nlp("/generate-page", {**payload, "structure_corrections": corrections}, timeout=_GENERATE_PAGE_TIMEOUT)

    return await structure_gate.apply_structure_gate(
        result,
        reference_analysis,
        _regenerate,
        enabled=settings.local_seo_structure_gate_enabled,
        min_composite=settings.local_seo_structure_min_composite,
        max_passes=settings.local_seo_structure_max_passes,
        log_tag="local_seo.structure_gate",
    )


def _resolve_page_spec(
    client: dict, keyword: str, location: str, location_code: Optional[int],
    serp: Optional[dict], fallback_target: Optional[int],
) -> Optional[dict]:
    """The page spec this generation is written against (plan §6 Phase 1):
    the active stored version (an edit sticks), else a freshly built + saved
    one. Best-effort — None on any failure, and generation carries on exactly
    as before (a page must never fail because its spec couldn't be built)."""
    try:
        return page_spec_store.resolve_spec(
            client, keyword, location, location_code, serp, fallback_target,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        logger.warning(
            "local_seo.page_spec_unavailable",
            extra={"client_id": client.get("id"), "keyword": keyword, "error": str(exc)},
        )
        return None


def attach_length_verdict(result: dict, spec: Optional[dict]) -> dict:
    """Measure the generated page against its spec and record the verdict on
    the result: `length_verdict` (full), plus the flat fields `_persist_page`
    writes to the page row. Pure apart from the HTML parse; a missing spec
    leaves the result untouched."""
    if not spec:
        return result
    try:
        measure = page_spec.measure_page(result.get("content_html") or "", spec)
        verdict = page_spec.length_verdict(measure, spec)
    except Exception as exc:  # noqa: BLE001 — measurement must never break the run
        logger.warning("local_seo.length_verdict_failed", extra={"error": str(exc)})
        return result
    result["length_verdict"] = {**verdict, "sections": measure.get("sections") or []}
    result["page_spec_id"] = spec.get("id")
    result["spec_version"] = spec.get("version")
    result["target_words"] = verdict.get("target_words")
    result["actual_words"] = verdict.get("total_words")
    result["length_status"] = verdict.get("status")
    return result


async def generate_page(
    client_id: str, keyword: str, location: str, location_code: Optional[int],
    user_id: str, force_refresh: bool = False,
    page_template_url: Optional[str] = None,
    include_decision_map: bool = True,
    notes: Optional[str] = None,
    entity_provider: Optional[str] = None,
    on_progress: Optional[Callable[[Optional[int], Optional[str]], Awaitable[None]]] = None,
    internal_links: Optional[list[dict]] = None,
) -> dict:
    """Generate a local SEO page for a client and persist it.

    `internal_links` (``[{anchor, url, relation}]``, from the service × location
    matrix) is handed to the writer as a prompt block AND guaranteed afterwards:
    any link the writer dropped is appended deterministically
    (`local_seo_matrix.ensure_internal_links`) and the coverage is returned on
    the page dict as ``link_coverage`` (not a page column — the matrix cell keeps it).

    The location is resolved/validated first: a mistyped area (no picked code)
    that can't be matched fails loudly (400). Competitor SERP analysis always
    runs first: it's pulled from the shared cache (or computed + cached once)
    and passed to nlp so the generator doesn't re-scrape. If the analysis itself
    fails (e.g. thin SERP / provider outage), generation degrades to a
    no-competitor page rather than failing outright — and run_analysis is
    flipped off in the nlp payload so nlp doesn't re-attempt the same failing
    scrape."""
    client = _get_client(client_id)
    location, location_code = await locations_service.resolve_location(client, location, location_code)
    payload = _gbp_to_generate_payload(
        client, keyword, location, location_code, include_decision_map=include_decision_map,
        entity_provider=entity_provider,
    )
    # The client's brand guide, distilled into enforceable rules (cached per
    # guide revision). Steers generation and drives the deterministic post-write
    # check; an empty card means the client has no guide and nothing changes.
    # Imported lazily: voice_card_service -> brand_voice_service -> this module
    # would close an import cycle at module scope.
    from services import voice_card_service

    payload["voice_card"] = await voice_card_service.get_voice_card(client, user_id=user_id)
    # SERP analysis FIRST: its length target (SERP avg + 20%, floored) both drives
    # the writer's word budget AND rescales the reference layout below, so a long
    # client reference page can't drag generation to ~2x the SERP-appropriate
    # length. Best-effort — a thin SERP / provider outage degrades to a
    # no-competitor page (run_analysis off so nlp doesn't re-scrape the failure).
    serp = await _get_or_compute_analysis(
        keyword, location, location_code, force_refresh, user_id, required=False,
        entity_provider=entity_provider,
    )
    if serp is None and settings.local_seo_analysis_retry_delay_seconds > 0:
        # One retry: the failure seen in practice is a seconds-long nlp restart
        # window (a redeploy), not a lasting provider outage.
        logger.warning(
            "local_seo.analysis_retry",
            extra={"client_id": client_id, "keyword": keyword,
                   "delay_s": settings.local_seo_analysis_retry_delay_seconds},
        )
        await asyncio.sleep(settings.local_seo_analysis_retry_delay_seconds)
        serp = await _get_or_compute_analysis(
            keyword, location, location_code, force_refresh, user_id, required=False,
            entity_provider=entity_provider,
        )
    analysis_ok = serp is not None
    if analysis_ok:
        payload["serp_analysis"] = serp
    else:
        payload["run_analysis"] = False  # analysis unavailable → degrade, no nlp re-scrape
    serp_target = (serp or {}).get("serp_word_target")
    if not serp_target:
        # No measured SERP length (analysis failed, or too few competitor pages
        # to average): the page must still be budgeted + graded on length, else
        # the writer falls back to the template's per-section counts and ships
        # 2–3× the market's length. Use the market's standing target.
        serp_target = _resolve_fallback_length_target(location_code, location)
        payload["length_target"] = serp_target
        logger.warning(
            "local_seo.length_target_fallback",
            extra={"client_id": client_id, "keyword": keyword, "target": serp_target,
                   "analysis_ok": analysis_ok},
        )
        if not analysis_ok:
            _notify_analysis_degraded(client_id, keyword, location, serp_target)

    # The kept page spec (length band + per-section bands + caps) for this
    # keyword × location — built from the same SERP analysis + the client's
    # reference layout, or the active edited version. Rides to nlp on the
    # payload (consumed in Phase 2); its target also drives the reference
    # scaling below so prompt and spec agree on the page size.
    spec = _resolve_page_spec(client, keyword, location, location_code, serp, serp_target)
    if spec:
        payload["page_spec"] = spec
        serp_target = (spec.get("total") or {}).get("target") or serp_target

    # Page template: per-page value wins; otherwise the client's saved default.
    template_url = (page_template_url or "").strip() or client.get("local_seo_page_template_url")
    reference_analysis: Optional[dict] = None
    if template_url:
        payload["page_template_url"] = template_url
    else:
        # No explicit template — mirror the client's own local page layout from
        # the pre-analyzed reference structures (local landing preferred, else
        # location). Avoids re-scraping a template URL at generate time. The
        # layout is rescaled to the SERP length target so the writer reproduces
        # the client's STRUCTURE at SERP-appropriate length, not the reference's
        # own (often much longer) word counts. Hold onto the winning entry's
        # analysis — scaled to the SAME target — so the structural gate scores the
        # output against the sizes the prompt asked for and never re-inflates it.
        from services.page_structure_render import (
            render_reference_structure, usable_analysis, scale_analysis_words,
        )

        structures = client.get("page_structures") or {}
        for page_type in ("local_landing", "location"):
            rendered = render_reference_structure(
                structures.get(page_type), page_type, target_words=serp_target,
            )
            if rendered:
                payload["reference_page_structure"] = rendered
                reference_analysis = scale_analysis_words(
                    usable_analysis(structures.get(page_type)), serp_target,
                )
                break
    if (notes or "").strip():
        payload["notes"] = notes.strip()  # per-page writing guidance the writer follows
    if internal_links:
        payload["internal_links"] = internal_links
    result = await _stream_nlp("/generate-page", payload, timeout=_GENERATE_PAGE_TIMEOUT, on_progress=on_progress)
    result = await _apply_structure_gate(result, payload, reference_analysis)
    coverage = _guarantee_internal_links(result, internal_links)
    result = attach_length_verdict(result, spec)
    # Record whether competitor analysis actually informed this page (it used
    # to be hard-coded True, so a degraded page was indistinguishable on read).
    page = _persist_page(client_id, keyword, location, analysis_ok, "generate", result, user_id, notes=notes)
    if result.get("length_verdict") is not None:
        page["length_verdict"] = result["length_verdict"]  # not a column — rides the response
    if coverage is not None:
        page["link_coverage"] = coverage
    return page


def _guarantee_internal_links(result: dict, internal_links: Optional[list[dict]]) -> Optional[dict]:
    """The matrix's link guarantee: after the writer (and every scoring /
    corrective pass) is done, append any sibling link it dropped as a compact
    block and return the coverage. Runs AFTER the structural gate so the appended
    list never counts against the reference-layout score. None when there were
    no links to guarantee."""
    if not internal_links:
        return None
    from services import local_seo_matrix

    html, coverage = local_seo_matrix.ensure_internal_links(result.get("content_html") or "", internal_links)
    result["content_html"] = html
    return coverage


# ── background generation (async job) ────────────────────────────────────────
# Generation takes minutes; running it as an async_jobs job (rather than a
# blocking SSE stream) lets the UI kick it off and navigate away — even to other
# clients — while it runs server-side. The page lands in the client's pages when
# done; the UI polls get_generate_job for status.

async def enqueue_generate(
    client_id: str, keyword: str, location: str, location_code: Optional[int],
    user_id: str, page_template_url: Optional[str] = None, force_refresh: bool = False,
    entity_provider: Optional[str] = None,
) -> str:
    """Validate the area, then enqueue a `local_seo_generate` job. Returns the job
    id. The location is resolved up front so a mistyped area fails fast (400) before
    the job is created, instead of failing silently in the background."""
    client = _get_client(client_id)
    location, location_code = await locations_service.resolve_location(client, location, location_code)
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "local_seo_generate",
                "entity_id": client_id,
                "payload": {
                    "client_id": client_id,
                    "keyword": keyword.strip(),
                    "location": location,
                    "location_code": location_code,
                    "user_id": user_id,
                    "page_template_url": (page_template_url or "").strip() or None,
                    "force_refresh": bool(force_refresh),
                    "entity_provider": entity_provider,
                },
            }
        )
        .execute()
    )
    return res.data[0]["id"]


async def run_generate_job(job: dict) -> None:
    """async_jobs handler for job_type='local_seo_generate'. Runs generate_page
    (which persists the page) and stores the new page id in the job result."""
    payload = job.get("payload") or {}
    job_id = job["id"]
    supabase = get_supabase()
    try:
        page = await generate_page(
            client_id=payload["client_id"],
            keyword=payload["keyword"],
            location=payload["location"],
            location_code=payload.get("location_code"),
            user_id=payload["user_id"],
            force_refresh=bool(payload.get("force_refresh")),
            page_template_url=payload.get("page_template_url"),
            entity_provider=payload.get("entity_provider"),
            on_progress=_job_progress_writer(job_id),
            internal_links=payload.get("internal_links") or None,
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"page_id": page["id"]}, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("local_seo.generate_job_complete", extra={"job_id": job_id, "page_id": page["id"]})
        # A matrix cell keeps the sibling-link coverage (plan §4.3). Best-effort:
        # the matrix reconciles the cell's status from this job row on read, so a
        # failed coverage write costs only the coverage detail, never the page.
        if payload.get("matrix_cell_id") and page.get("link_coverage") is not None:
            try:
                from services.local_seo_matrix_store import record_link_coverage

                record_link_coverage(payload["matrix_cell_id"], page["link_coverage"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("local_seo.matrix_link_coverage_failed", extra={"job_id": job_id, "error": str(exc)})
        # Drip release: generate THEN publish just-in-time (plan §5.2). The page
        # is already persisted + the job complete, so a publish failure costs
        # only the publish — it lands on the cell as publish_failed / blocked.
        if payload.get("publish_after"):
            await _publish_after_generate(page["id"], payload, job_id)
    except Exception as exc:  # noqa: BLE001 — record the failure for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("local_seo.generate_job_failed", extra={"job_id": job_id, "error": str(detail)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


async def _publish_after_generate(page_id: str, payload: dict, job_id: str) -> None:
    """The drip release's auto-publish: publish the just-generated page to the
    matrix's destination and record the outcome on the cell. Best-effort — never
    raises into the job (the page + job are already complete)."""
    from services import local_seo_matrix as core
    from services.local_seo_matrix_store import record_publish_outcome

    cell_id = payload.get("matrix_cell_id")
    destination = payload.get("publish_destination") or "google_docs"
    status = payload.get("publish_status") or "draft"
    try:
        result = await publish_page(page_id, payload.get("user_id") or "", destination=destination, status=status)
        outcome = core.publish_outcome_from_result(result or {})
    except HTTPException as exc:
        outcome = core.publish_outcome_from_error(str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        outcome = core.publish_outcome_from_error(str(exc))
    logger.info(
        "local_seo.matrix_publish_after",
        extra={"job_id": job_id, "page_id": page_id, "cell_id": cell_id, "outcome": outcome[0]},
    )
    if cell_id:
        try:
            record_publish_outcome(cell_id, page_id, *outcome)
        except Exception as exc:  # noqa: BLE001
            logger.warning("local_seo.matrix_publish_record_failed", extra={"job_id": job_id, "error": str(exc)})


def get_generate_job(job_id: str, client_id: str) -> dict:
    """Poll a generate job (scoped to the client). Returns
    {status, page_id, error}."""
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .select("status, result, error, entity_id")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="generate_job_not_found")
    row = res.data[0]
    result = row.get("result") or {}
    return {"status": row["status"], "page_id": result.get("page_id"), "error": row.get("error")}


# ── bulk background generation / reoptimization (per-item async jobs) ─────────
# Bulk flows enqueue ONE job per item (not one big batch job), for two reasons:
#   1. the stale-job reaper (`job_stale_timeout_minutes`, 30m) — each item stays
#      well under it, whereas a single ~90-min batch job would be reaped mid-run
#      and requeued, re-generating the items it had already finished; and
#   2. background priority — each item's `scheduled_at` is staggered into the
#      future (`_bulk_scheduled_at`), so the worker (which claims the oldest
#      `scheduled_at` with no <=now gate) interleaves now-dated interactive /
#      scheduled jobs ahead of the rest of a batch instead of the batch
#      monopolizing the single worker. Bulk still runs back-to-back when the
#      queue is otherwise empty (no gate = no artificial delay).
# The UI enqueues the set, polls get_jobs_status, and can leave at any time — the
# jobs keep running server-side and the pages land in the client's pages.

def _bulk_scheduled_at(index: int) -> str:
    """Staggered `scheduled_at` for the `index`-th item of a bulk run, so the
    worker (which claims the oldest scheduled_at, with no <=now gate) interleaves
    now-dated interactive/scheduled jobs ahead of the rest of the batch. No delay
    when the queue is otherwise empty. See `local_seo_bulk_job_spacing_seconds`."""
    spacing = settings.local_seo_bulk_job_spacing_seconds
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


async def enqueue_generate_bulk(
    client_id: str, keywords: list[str], location: str, location_code: Optional[int],
    user_id: str, page_template_url: Optional[str] = None, force_refresh: bool = False,
    entity_provider: Optional[str] = None,
) -> list[str]:
    """Enqueue one `local_seo_generate` job per keyword (area validated once up
    front). Returns the job ids in input order."""
    client = _get_client(client_id)
    location, location_code = await locations_service.resolve_location(client, location, location_code)
    template = (page_template_url or "").strip() or None
    rows = []
    for kw in keywords:
        if not (kw or "").strip():
            continue
        rows.append(
            {
                "job_type": "local_seo_generate",
                "entity_id": client_id,
                "scheduled_at": _bulk_scheduled_at(len(rows)),
                "payload": {
                    "client_id": client_id,
                    "keyword": kw.strip(),
                    "location": location,
                    "location_code": location_code,
                    "user_id": user_id,
                    "page_template_url": template,
                    "force_refresh": bool(force_refresh),
                    "entity_provider": entity_provider,
                },
            }
        )
    if not rows:
        return []
    res = get_supabase().table("async_jobs").insert(rows).execute()
    return [r["id"] for r in (res.data or [])]


async def enqueue_reoptimize_bulk(
    client_id: str, targets: list[dict], user_id: str,
    score_threshold: Optional[float] = None, publish_to_doc: bool = False,
    entity_provider: Optional[str] = None,
) -> list[dict]:
    """Enqueue one `local_seo_reoptimize_url` job per target. Each target is
    ``{page_url, keyword, location, location_code}``; the area is resolved inside
    the job (so a bad line fails its own row, not the batch). Returns
    ``[{job_id, page_url}]`` in input order."""
    _get_client(client_id)  # validate client exists
    threshold = REOPT_SCORE_THRESHOLD if score_threshold is None else score_threshold
    rows = []
    for t in targets:
        page_url = (t.get("page_url") or "").strip()
        if not page_url:
            continue
        rows.append(
            {
                "job_type": "local_seo_reoptimize_url",
                "entity_id": client_id,
                "scheduled_at": _bulk_scheduled_at(len(rows)),
                "payload": {
                    "client_id": client_id,
                    "page_url": page_url,
                    "keyword": (t.get("keyword") or "").strip(),
                    "location": (t.get("location") or "").strip(),
                    "location_code": t.get("location_code"),
                    "user_id": user_id,
                    "score_threshold": threshold,
                    "publish_to_doc": bool(publish_to_doc),
                    "entity_provider": entity_provider,
                },
            }
        )
    if not rows:
        return []
    res = get_supabase().table("async_jobs").insert(rows).execute()
    return [
        {"job_id": r["id"], "page_url": rows[i]["payload"]["page_url"]}
        for i, r in enumerate(res.data or [])
    ]


async def run_reoptimize_url_job(job: dict) -> None:
    """async_jobs handler for job_type='local_seo_reoptimize_url'. Runs
    reoptimize_url and stores its full result dict (status reoptimized/skipped +
    scores) in the job result."""
    payload = job.get("payload") or {}
    job_id = job["id"]
    supabase = get_supabase()
    try:
        result = await reoptimize_url(
            client_id=payload["client_id"],
            page_url=payload["page_url"],
            keyword=payload["keyword"],
            location=payload["location"],
            location_code=payload.get("location_code"),
            user_id=payload["user_id"],
            score_threshold=payload.get("score_threshold", REOPT_SCORE_THRESHOLD),
            publish_to_doc=bool(payload.get("publish_to_doc")),
            entity_provider=payload.get("entity_provider"),
            on_progress=_job_progress_writer(job_id),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("local_seo.reoptimize_job_complete", extra={"job_id": job_id})
    except Exception as exc:  # noqa: BLE001 — record the failure for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("local_seo.reoptimize_job_failed", extra={"job_id": job_id, "error": str(detail)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def get_jobs_status(client_id: str, job_ids: list[str]) -> list[dict]:
    """Batch poll a set of jobs (scoped to the client). Returns
    ``[{job_id, status, result, error}]`` for the jobs that belong to the client."""
    if not job_ids:
        return []
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .select("id, status, result, error, entity_id, progress, progress_message")
        .in_("id", job_ids)
        .execute()
    )
    out = []
    for row in res.data or []:
        if row.get("entity_id") != client_id:
            continue
        out.append(
            {"job_id": row["id"], "status": row["status"], "result": row.get("result"),
             "error": row.get("error"),
             "progress": row.get("progress"), "progress_message": row.get("progress_message")}
        )
    return out


async def enqueue_reoptimize_page(
    client_id: str, keyword: str, location: str,
    existing_page_html: Optional[str], existing_page_url: Optional[str],
    deficiencies: list[dict], serp_analysis: Optional[dict], user_id: str,
    entity_provider: Optional[str] = None,
    internal_links: Optional[list[dict]] = None,
) -> str:
    """Enqueue a background reoptimize-by-page job (the score→reoptimize flow).
    Returns the job id. A single interactive reoptimize, so it's NOT staggered —
    it gets default `scheduled_at` (now) and runs at normal priority. The poller
    reads the new page id from the job result (via get_jobs_status)."""
    _get_client(client_id)  # validate client exists
    res = (
        get_supabase()
        .table("async_jobs")
        .insert(
            {
                "job_type": "local_seo_reoptimize_page",
                "entity_id": client_id,
                "payload": {
                    "client_id": client_id,
                    "keyword": keyword,
                    "location": location,
                    "existing_page_html": existing_page_html,
                    "existing_page_url": existing_page_url,
                    "deficiencies": deficiencies or [],
                    "serp_analysis": serp_analysis,
                    "user_id": user_id,
                    "entity_provider": entity_provider,
                    "internal_links": internal_links or None,
                },
            }
        )
        .execute()
    )
    return res.data[0]["id"]


async def run_reoptimize_page_job(job: dict) -> None:
    """async_jobs handler for job_type='local_seo_reoptimize_page'. Runs
    reoptimize_page (which persists the reoptimized page) and stores the new page
    id in the job result."""
    payload = job.get("payload") or {}
    job_id = job["id"]
    supabase = get_supabase()
    try:
        page = await reoptimize_page(
            client_id=payload["client_id"],
            keyword=payload["keyword"],
            location=payload["location"],
            existing_page_html=payload.get("existing_page_html"),
            existing_page_url=payload.get("existing_page_url"),
            deficiencies=payload.get("deficiencies") or [],
            serp_analysis=payload.get("serp_analysis"),
            user_id=payload["user_id"],
            entity_provider=payload.get("entity_provider"),
            on_progress=_job_progress_writer(job_id),
            internal_links=payload.get("internal_links") or None,
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"page_id": page["id"]}, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("local_seo.reoptimize_page_job_complete", extra={"job_id": job_id, "page_id": page["id"]})
    except Exception as exc:  # noqa: BLE001 — record the failure for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("local_seo.reoptimize_page_job_failed", extra={"job_id": job_id, "error": str(detail)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


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


async def check_rankability(
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    sab_city: Optional[str],
    user_id: Optional[str] = None,
) -> dict:
    """Map-pack rankability report for a keyword + location.

    Resolves/validates the area, builds the rankability payload from the client's
    stored GBP, and proxies to the private nlp `/check-rankability`. The report is
    a single point-in-time, non-streaming check (no LLM) so it returns plain JSON.
    """
    client = _get_client(client_id)
    if not _business_fields(client)["gbp_category"]:
        raise HTTPException(status_code=400, detail="client_has_no_gbp_category")
    location, location_code = await locations_service.resolve_location(client, location, location_code)
    payload = _gbp_to_rankability_payload(client, keyword, location, location_code, sab_city)
    return await _post_nlp("/check-rankability", payload, user_id=user_id)


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
    entity_provider: Optional[str] = None,
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
            keyword, location, location_code, force_refresh, user_id, required=False,
            entity_provider=entity_provider,
        )
    from services import voice_card_service

    result = await _post_nlp("/score-page", {
        "keyword": keyword,
        "location": location,
        "location_code": location_code,
        "page_url": page_url,
        "page_content": page_content,
        "business_name": fields["business_name"],
        "gbp_category": fields["gbp_category"],
        "address": fields["address"],
        "serp_analysis": serp_analysis,
        "entity_provider": entity_provider,
        # Without these the rubric measured SEO only: icp_alignment inferred an
        # audience from the keyword and nothing scored brand voice at all.
        "voice_card": await voice_card_service.get_voice_card(client, user_id=user_id),
    }, user_id=user_id)
    # A standalone score has no page row — log it against page_url (may be None
    # when scoring raw HTML) so the verdict is still kept in the run history.
    _record_score_run(
        client_id, keyword, location, "score", result,
        page_id=None, page_url=page_url, user_id=user_id,
    )
    return result


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
    entity_provider: Optional[str] = None,
    on_progress: Optional[Callable[[Optional[int], Optional[str]], Awaitable[None]]] = None,
    internal_links: Optional[list[dict]] = None,
) -> dict:
    """Reoptimize an existing page to lift its score, re-score the result, and
    persist it as a `mode='reoptimize'` row. `internal_links` (matrix sibling
    pages) are kept through the rewrite and guaranteed afterwards, exactly as on
    generate — a reoptimize pass must not strip the silo."""
    client = _get_client(client_id)
    fields = _business_fields(client)
    if not existing_page_html and not existing_page_url:
        raise HTTPException(status_code=400, detail="page_url_or_html_required")

    from services import voice_card_service

    # Reoptimize never used to receive the brand guide, so each pass rewrote the
    # page without it — a page generated in the client's voice drifted further
    # from them with every improvement to its score.
    voice_card = await voice_card_service.get_voice_card(client, user_id=user_id)

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
        "entity_provider": entity_provider,
        "voice_card": voice_card,
        # Keep the decision-fit treatment on reoptimization (parity with generate).
        "include_decision_map": True,
        "internal_links": internal_links or None,
    }, on_progress=on_progress)
    link_coverage = _guarantee_internal_links(result, internal_links)

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
                "entity_provider": entity_provider,
                "voice_card": voice_card,
            })
            result["composite_score"] = score.get("composite_score")
            result["composite_status"] = score.get("composite_status")
            result["engine_scores"] = score.get("engine_scores")
            result["deficiencies"] = score.get("deficiencies")
            result.setdefault("voice_compliance", score.get("voice_compliance"))
        except Exception:
            # Non-fatal — the expensive rewrite already succeeded, so persist the
            # reoptimized page without a fresh score rather than losing the work.
            # (Catches HTTPException from the proxy AND any decode/unexpected error.)
            logger.warning("local_seo.reoptimize_rescore_failed", extra={"client_id": client_id})

    page = _persist_page(client_id, keyword, location, bool(serp_analysis), "reoptimize", result, user_id)
    if link_coverage is not None:
        page["link_coverage"] = link_coverage
    return page


# Pages scoring at/above this are already strong enough that a rewrite isn't
# worth the cost — the batch reoptimizer skips them with a note instead. Product
# default; overridable per request via `score_threshold`.
REOPT_SCORE_THRESHOLD = 75.0


async def reoptimize_url(
    client_id: str,
    page_url: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    user_id: str,
    score_threshold: float = REOPT_SCORE_THRESHOLD,
    publish_to_doc: bool = False,
    entity_provider: Optional[str] = None,
    on_progress: Optional[Callable[[Optional[int], Optional[str]], Awaitable[None]]] = None,
) -> dict:
    """Score a live page (by URL) and reoptimize it only if it scores below
    `score_threshold`. Strong pages (>= threshold) are skipped with a note rather
    than rewritten. Optionally publishes each reoptimized page to a Google Doc.

    Backs the Reoptimization tab's single + bulk URL flows. The SERP analysis is
    computed once and reused for both the score and the rewrite so neither
    re-scrapes. Returns one of:

      {"status": "skipped",     "page_url", "keyword", "score", "threshold", "reason"}
      {"status": "reoptimized", "page_url", "keyword", "prev_score", "new_score",
                                "page": {id, page_title, composite_score, ...},
                                ["published": {...}] | ["publish_error": str]}
    """
    client = _get_client(client_id)
    fields = _business_fields(client)
    location, location_code = await locations_service.resolve_location(client, location, location_code)

    # Coarse progress for the pre-rewrite phase (analysis + score are plain JSON
    # calls with no SSE of their own). The rewrite itself streams fine-grained
    # progress once reoptimize_page takes over.
    if on_progress is not None:
        await on_progress(8, "Analyzing the SERP & scoring the live page…")

    # Shared SERP analysis (served from cache when fresh) — passed to both the
    # score and the rewrite so neither re-scrapes. Optional: both degrade
    # gracefully without it (required=False).
    serp = await _get_or_compute_analysis(
        keyword, location, location_code, force_refresh=False, user_id=user_id, required=False,
        entity_provider=entity_provider,
    )

    from services import voice_card_service

    score_result = await _post_nlp("/score-page", {
        "keyword": keyword,
        "location": location,
        "location_code": location_code,
        "page_url": page_url,
        "page_content": None,
        "business_name": fields["business_name"],
        "gbp_category": fields["gbp_category"],
        "address": fields["address"],
        "serp_analysis": serp,
        "entity_provider": entity_provider,
        "voice_card": await voice_card_service.get_voice_card(client, user_id=user_id),
    }, user_id=user_id)

    # Record the "before" verdict of the live page (whether or not we go on to
    # reoptimize) so the history captures what the page scored at as found.
    _record_score_run(
        client_id, keyword, location, "reoptimize_before", score_result,
        page_id=None, page_url=page_url, user_id=user_id,
    )

    composite = score_result.get("composite_score")
    voice_compliance = score_result.get("voice_compliance")
    # Gate: skip only when the page clears BOTH bars. Deciding on the SEO score
    # alone silently skipped the pages most worth rewriting — a page at 78 SEO
    # and 40 voice never had its voice score looked at.
    should_reopt, reason = voice_card_service.reoptimize_verdict(
        composite, voice_compliance, score_threshold,
        length_fit=(score_result.get("engine_scores") or {}).get("length_fit"),
    )
    voice_score = (voice_compliance or {}).get("score")
    if not should_reopt:
        logger.info(
            "local_seo.reoptimize_url_skipped",
            extra={
                "client_id": client_id, "page_url": page_url,
                "score": composite, "voice_score": voice_score,
            },
        )
        return {
            "status": "skipped",
            "page_url": page_url,
            "keyword": keyword,
            "score": composite,
            "voice_score": voice_score,
            "threshold": score_threshold,
            "reason": reason,
        }
    logger.info(
        "local_seo.reoptimize_url_proceeding",
        extra={
            "client_id": client_id, "page_url": page_url,
            "score": composite, "voice_score": voice_score, "reason": reason,
        },
    )

    # Below either threshold (or unscoreable) → reoptimize. Reuses the shared op, which
    # rewrites + re-scores + persists the page as a mode='reoptimize' row.
    page = await reoptimize_page(
        client_id=client_id,
        keyword=keyword,
        location=location,
        existing_page_html=None,
        existing_page_url=page_url,
        deficiencies=score_result.get("deficiencies") or [],
        serp_analysis=serp,
        user_id=user_id,
        entity_provider=entity_provider,
        on_progress=on_progress,
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
        # The page is already saved in-app, so ANY publish failure is non-fatal —
        # surface it per-row rather than failing the whole reoptimize. Catch broadly
        # (not just HTTPException): publish_page's final published_doc_url update is
        # unwrapped, so a transient DB error there must not lose the saved rewrite.
        try:
            pub = await publish_page(page["id"], user_id)
            out["published"] = {"doc_url": pub.get("doc_url"), "doc_id": pub.get("doc_id")}
            out["page"]["published_doc_url"] = pub.get("doc_url")
        except Exception as exc:
            out["publish_error"] = str(getattr(exc, "detail", None) or exc or "publish_failed")
            logger.warning(
                "local_seo.reoptimize_url_publish_failed",
                extra={"client_id": client_id, "page_id": page["id"], "error": str(exc)},
            )

    return out


async def social_posts(
    client_id: str,
    keyword: str,
    location: str,
    page_content: str,
    serp_analysis: Optional[dict],
    page_id: Optional[str] = None,
) -> dict:
    """Generate GBP social posts from a generated page's text. When ``page_id`` is
    given, save the result on the page so re-opening the tab re-reads it instead
    of regenerating (an explicit Regenerate overwrites)."""
    client = _get_client(client_id)
    fields = _business_fields(client)
    result = await _post_nlp("/generate-social-posts", {
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
    if page_id and isinstance(result, dict):
        try:
            get_supabase().table("local_seo_pages").update(
                {"social_posts": result, "updated_at": "now()"}
            ).eq("id", page_id).eq("client_id", client_id).execute()
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            logger.warning("local_seo.social_posts_save_failed",
                           extra={"page_id": page_id, "error": str(exc)[:200]})
    return result


# ── interactive actions as background jobs ───────────────────────────────────
# precheck / analyze / find-page / score / related-pages / social-posts used to
# be heartbeat-SSE streams: from the user's view the work died the moment they
# navigated away (the connection dropped and there was no job to poll back into).
# Enqueued as `local_seo_action` jobs instead, they run to completion in the
# worker and their result dict is stored on the job row, so the UI can leave and
# reconnect (poll get_jobs_status) to pick the result up — matching how
# generate / reoptimize already behave.

_ACTION_JOB_TYPE = "local_seo_action"


async def enqueue_action(client_id: str, action: str, args: dict, user_id: str) -> str:
    """Enqueue a `local_seo_action` job (precheck/analyze/find_page/score/
    related_pages/social_posts). Returns the job id. The client is validated up
    front so a bad id fails fast (404) before the job is created; the poller reads
    the result via get_jobs_status."""
    _get_client(client_id)  # validate ownership / existence
    res = (
        get_supabase()
        .table("async_jobs")
        .insert(
            {
                "job_type": _ACTION_JOB_TYPE,
                "entity_id": client_id,
                "payload": {
                    "client_id": client_id,
                    "action": action,
                    "args": args or {},
                    "user_id": user_id,
                },
            }
        )
        .execute()
    )
    return res.data[0]["id"]


async def _run_action(action: str, client_id: str, args: dict, user_id: str) -> dict:
    """Dispatch a local_seo_action to the matching service call; returns its
    JSON-serializable result dict (stored on the job row and polled by the UI)."""
    if action == "precheck":
        from services import local_seo_precheck
        from models.local_seo import LocalSeoPrecheckResult
        result = await local_seo_precheck.detect_existing_pages(
            client_id=client_id, keyword=args["keyword"], location=args["location"],
            location_code=args.get("location_code"), user_id=user_id,
        )
        return LocalSeoPrecheckResult(**result).model_dump(mode="json")
    if action == "analyze":
        return await analyze(
            client_id=client_id, keyword=args["keyword"], location=args["location"],
            location_code=args.get("location_code"), force_refresh=bool(args.get("force_refresh")),
        )
    if action == "find_page":
        return await find_page(client_id=client_id, keyword=args["keyword"], location=args["location"])
    if action == "score":
        return await score_page(
            client_id=client_id, keyword=args["keyword"], location=args["location"],
            location_code=args.get("location_code"), page_url=args.get("page_url"),
            page_content=args.get("page_content"), serp_analysis=args.get("serp_analysis"),
            user_id=user_id, force_refresh=bool(args.get("force_refresh")),
            entity_provider=args.get("entity_provider"),
        )
    if action == "related_pages":
        return await related_pages(client_id=client_id, keyword=args["keyword"], location=args["location"])
    if action == "social_posts":
        return await social_posts(
            client_id=client_id, keyword=args["keyword"], location=args["location"],
            page_content=args["page_content"], serp_analysis=args.get("serp_analysis"),
            page_id=args.get("page_id"),
        )
    raise HTTPException(status_code=400, detail="unknown_local_seo_action")


async def run_local_seo_action_job(job: dict) -> None:
    """async_jobs handler for job_type='local_seo_action'. Runs the interactive
    action in the background and stores its result dict on the job row (polled via
    get_jobs_status), so the UI survives navigating away."""
    payload = job.get("payload") or {}
    action = payload.get("action")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        result = await _run_action(
            action, payload["client_id"], payload.get("args") or {}, payload.get("user_id"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("local_seo.action_job_complete", extra={"job_id": job_id, "action": action})
    except Exception as exc:  # noqa: BLE001 — record the failure for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning(
            "local_seo.action_job_failed",
            extra={"job_id": job_id, "action": action, "error": str(detail)},
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


# Columns returned for the page-list views (Saved Pages + Drafts).
_LIST_COLUMNS = (
    "id, client_id, keyword, location, page_title, composite_score, "
    "composite_status, voice_score, mode, created_at, deleted_at, "
    "published_doc_url, published_url, published_at, "
    "target_words, actual_words, length_status"
)


def list_pages(client_id: str, deleted: bool = False) -> list[dict]:
    """List a client's Local SEO pages. ``deleted=False`` → active (Saved Pages);
    ``deleted=True`` → soft-deleted (Drafts). Drafts order by when they were
    deleted (most recently binned first), active pages by creation."""
    supabase = get_supabase()
    query = (
        supabase.table("local_seo_pages")
        .select(_LIST_COLUMNS)
        .eq("client_id", client_id)
    )
    if deleted:
        query = query.not_.is_("deleted_at", "null").order("deleted_at", desc=True)
    else:
        query = query.is_("deleted_at", "null").order("created_at", desc=True)
    return query.execute().data or []


def get_page(page_id: str) -> dict:
    supabase = get_supabase()
    res = supabase.table("local_seo_pages").select("*").eq("id", page_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="local_seo_page_not_found")
    return res.data


def list_score_history(
    client_id: str, page_id: Optional[str] = None, limit: int = 100,
) -> list[dict]:
    """Return a client's score-run history (newest first), including the full
    per-engine `engine_scores` verdict for each run. Optionally scoped to one
    page. `limit` is clamped to a sane ceiling."""
    limit = max(1, min(limit, 500))
    supabase = get_supabase()
    query = (
        supabase.table("local_seo_page_scores")
        .select("*")
        .eq("client_id", client_id)
    )
    if page_id:
        query = query.eq("page_id", page_id)
    return query.order("created_at", desc=True).limit(limit).execute().data or []


def delete_page(page_id: str) -> None:
    """Soft-delete: move the page to Drafts (set deleted_at). Recoverable via
    restore_page; permanent removal is purge_page."""
    supabase = get_supabase()
    res = (
        supabase.table("local_seo_pages")
        .update({"deleted_at": "now()"})
        .eq("id", page_id)
        .is_("deleted_at", "null")  # idempotent: don't re-stamp an already-drafted page
        .execute()
    )
    if not res.data:
        # Either it doesn't exist, or it's already in Drafts — treat both as 404
        # only when the row truly isn't there.
        existing = supabase.table("local_seo_pages").select("id").eq("id", page_id).execute().data
        if not existing:
            raise HTTPException(status_code=404, detail="local_seo_page_not_found")
    logger.info("local_seo.page_drafted", extra={"page_id": page_id})


def restore_page(page_id: str) -> dict:
    """Restore a drafted page back to Saved Pages (clear deleted_at)."""
    supabase = get_supabase()
    res = (
        supabase.table("local_seo_pages")
        .update({"deleted_at": None})
        .eq("id", page_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="local_seo_page_not_found")
    logger.info("local_seo.page_restored", extra={"page_id": page_id})
    return res.data[0]


def purge_page(page_id: str) -> None:
    """Permanently delete a page (from the Drafts tab). Irreversible."""
    supabase = get_supabase()
    res = supabase.table("local_seo_pages").delete().eq("id", page_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="local_seo_page_not_found")
    logger.info("local_seo.page_purged", extra={"page_id": page_id})


def purge_drafts(client_id: str) -> int:
    """Permanently delete ALL of a client's drafted pages. Returns the count
    removed. Irreversible — only deleted_at-stamped rows are touched."""
    supabase = get_supabase()
    res = (
        supabase.table("local_seo_pages")
        .delete()
        .eq("client_id", client_id)
        .not_.is_("deleted_at", "null")
        .execute()
    )
    count = len(res.data or [])
    logger.info("local_seo.drafts_purged", extra={"client_id": client_id, "count": count})
    return count


def set_featured_image(page_id: str, url: Optional[str]) -> dict:
    """Attach (or clear, when url is falsy) a page's featured/hero image."""
    supabase = get_supabase()
    res = (
        supabase.table("local_seo_pages")
        .update({"featured_image_url": url or None})
        .eq("id", page_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="local_seo_page_not_found")
    return {"featured_image_url": url or None}


async def _publish_page_to_github(page: dict, client: dict, user_id: str) -> dict:
    """Commit a Local SEO page to the client's GitHub repo as a content Markdown
    file. The page body is HTML (valid inside a Markdown file), wrapped with
    frontmatter by the shared github service."""
    from services.github_publish import GitHubPublishError, publish_to_github

    title = page.get("page_title") or f"{page.get('keyword', '')} — {client.get('name', '')}"
    html = page.get("content_html") or ""
    # Route through the per-type path + deep-nesting logic: a Local SEO page is a
    # location landing page carrying an explicit location column, so pass both.
    keyword = page.get("keyword", "") or ""
    location = page.get("location", "") or ""
    try:
        result = await publish_to_github(
            client=client,
            title=title,
            body=html,
            slug=keyword,
            content_type="local_seo_page",
            location=location,
            hero_image=page.get("featured_image_url"),
            schema=page.get("schema_json") or "",
        )
    except GitHubPublishError as exc:
        client_errors = {"github_not_configured", "github_repo_not_set", "content_is_empty"}
        code = 422 if str(exc) in client_errors else 502
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    logger.info(
        "local_seo.page_published_github",
        extra={"page_id": page["id"], "path": result.get("path"), "user_id": user_id},
    )
    return {
        "success": True,
        "destination": "github",
        "url": result.get("html_url"),
        "path": result.get("path"),
    }


async def _publish_page_to_wordpress(
    page: dict, client: dict, user_id: str, status: str
) -> dict:
    """Publish a Local SEO page straight to the client's WordPress site as a
    page (the content_html is already valid HTML — no conversion needed)."""
    supabase = get_supabase()
    title = page.get("page_title") or f"{page.get('keyword', '')} — {client.get('name', '')}"
    html = page.get("content_html") or ""
    try:
        result = await publish_to_wordpress(
            client=client,
            title=title,
            html=html,
            status=status,
            content_type="local_seo_page",
            featured_image_url=page.get("featured_image_url"),
        )
    except WordPressPublishError as exc:
        client_errors = {
            "wordpress_not_configured",
            "invalid_wordpress_site_url",
            "wordpress_site_url_must_be_https",
            "invalid_status",
            "content_is_empty",
        }
        code = 422 if str(exc) in client_errors else 502
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    supabase.table("local_seo_pages").update({
        "published_url": result.get("link"),
        "published_at": "now()",
    }).eq("id", page["id"]).execute()
    logger.info(
        "local_seo.page_published_wordpress",
        extra={"page_id": page["id"], "post_id": result.get("post_id"), "user_id": user_id},
    )
    return {
        "success": True,
        "destination": "wordpress",
        "post_id": result.get("post_id"),
        "url": result.get("link"),
        "edit_url": result.get("edit_link"),
        "status": result.get("status"),
    }


async def publish_page(
    page_id: str,
    user_id: str,
    destination: str = "google_docs",
    status: str = "draft",
    force_voice: bool = False,
) -> dict:
    """Publish a saved Local SEO page to a Google Doc in the client's Drive folder
    via the Apps Script webhook (same path as the blog writer), or directly to the
    client's WordPress site (destination='wordpress'). For Google Docs the page's
    HTML is converted to Markdown (the webhook's expected `content` format); for
    WordPress the HTML is posted as-is. The publish target is persisted on the row."""
    # Fail fast on unconfigured Google Docs before any DB work.
    if destination == "google_docs" and not settings.google_apps_script_url:
        raise HTTPException(status_code=503, detail="publish_not_configured")

    supabase = get_supabase()
    page = get_page(page_id)  # 404s if missing

    # A page that breaks the brand guide does not go out. Checked here rather
    # than per-destination so Docs, WordPress and GitHub are all covered.
    from services import voice_card_service

    voice_card_service.assert_voice_publishable(page.get("voice_violations"), force_voice)

    # Regulatory guardrail (peptide/regulated clients): block content that gives
    # human dosing instructions, claims branded-drug equivalence, promises
    # guaranteed results, or advocates buying. No-op for unregulated clients.
    if settings.content_compliance_enabled:
        from services import content_compliance

        client_mode = (supabase.table("clients").select("content_compliance_mode")
                       .eq("id", page["client_id"]).single().execute().data) or {}
        content_compliance.assert_content_publishable(
            client_mode,
            title=page.get("title") or page.get("keyword") or "",
            body=page.get("content_html") or "",
        )

    if destination == "github":
        client_res = (
            supabase.table("clients")
            .select(
                "name, github_repo, github_branch, github_content_path, "
                "github_content_paths, github_inferred_patterns, "
                "business_location, target_cities, gbp"
            )
            .eq("id", page["client_id"])
            .single()
            .execute()
        )
        if not client_res.data:
            raise HTTPException(status_code=404, detail="client_not_found")
        return await _publish_page_to_github(page, client_res.data, user_id)

    if destination == "wordpress":
        client_res = (
            supabase.table("clients")
            .select(
                "name, wordpress_site_url, wordpress_username, wordpress_app_password"
            )
            .eq("id", page["client_id"])
            .single()
            .execute()
        )
        if not client_res.data:
            raise HTTPException(status_code=404, detail="client_not_found")
        return await _publish_page_to_wordpress(page, client_res.data, user_id, status)

    client_res = (
        supabase.table("clients")
        .select("name, google_drive_folder_id, drive_folders")
        .eq("id", page["client_id"])
        .single()
        .execute()
    )
    if not client_res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    folder_id = resolve_drive_folder(client_res.data, "local_seo_page")
    if not folder_id:
        raise HTTPException(status_code=422, detail="missing_google_drive_folder_id")

    # Send the page's HTML (not markdown) with format="html" so the Apps Script
    # builds a natively-formatted Doc that copy-pastes cleanly into WordPress.
    content_html = page.get("content_html") or ""
    if not content_html.strip():
        raise HTTPException(status_code=422, detail="page_is_empty")

    # Render the hero image at the top of the doc (the WordPress path handles it
    # as the post's featured image instead).
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
