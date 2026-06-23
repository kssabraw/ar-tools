"""Local SEO silo planner (#2) — Fanout-powered page-target discovery.

Replaces the shallow single-keyword `/related-pages` lookup behind the
"Plan Silo" tab with the Topic Fanout keyword-research pipeline: silo discovery
(LLM grounding + DataForSEO demand / competitor signals) → keyword expansion →
relevance gating → Louvain clustering. Each cluster representative becomes one
candidate local page target, grouped under its silo.

The pipeline is reused *by import* from the vendored Fanout backend
(`writer/platform-api/fanout/`); we inject Fanout's own DataForSEO client, LLM,
and embedding fn via its factories (`get_dataforseo` / `get_llm`). Tuning
differs from Fanout's session defaults so local-intent (geo-modified) keywords
survive: the relevance threshold is relaxed and the language gate is skipped —
the "let Fanout surface geo keywords" decision.

The full pipeline runs for minutes and bills DataForSEO/LLM, so it executes as
an `async_jobs` job (job_type='local_seo_silo'); the route enqueues + polls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import HTTPException

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Tuning for the local-SEO use of the Fanout pipeline. Smaller than Fanout's
# full-session defaults (this is a focused per-service plan, not a research
# session) to bound cost/latency; the relevance threshold is relaxed below
# Fanout's 0.62 so geo-modified variants ("…near me", "… <city>") survive.
_TOPIC_COUNT = 5
_RELEVANCE_THRESHOLD = 0.50
_KEYWORD_IDEAS_LIMIT = 300
_AUTOCOMPLETE_MAX = 300
_PAA_TIER1_SEEDS = 6
_PAA_TIER2_CAP = 24
# Cap candidate pages surfaced per silo so the bulk-create list stays usable.
_MAX_PAGES_PER_SILO = 12
# US fallback market when the area didn't resolve to a DataForSEO location_code.
_DEFAULT_LOCATION_CODE = 2840


def _get_client(client_id: str) -> dict:
    supabase = get_supabase()
    res = supabase.table("clients").select("*").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data


async def start_silo_plan(
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    user_id: str,
) -> str:
    """Validate the area, then enqueue a `local_seo_silo` job. Returns the job id.

    One plan in flight per client — a pending/running job is reused rather than
    stacking another expensive pipeline run."""
    from services import locations_service

    client = _get_client(client_id)
    canonical_location, resolved_code = await locations_service.resolve_location(
        client, location, location_code
    )

    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "local_seo_silo")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]

    res = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "local_seo_silo",
                "entity_id": client_id,
                "payload": {
                    "client_id": client_id,
                    "keyword": keyword.strip(),
                    "location": canonical_location,
                    "location_code": resolved_code,
                    "user_id": user_id,
                },
            }
        )
        .execute()
    )
    return res.data[0]["id"]


def get_silo_plan(job_id: str, client_id: str) -> dict:
    """Read a plan job's row. Returns {status, items, degraded_notes, error}.

    Scoped to the client (the job's `entity_id`) so a job id can't be polled
    across clients."""
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .select("status, result, error, entity_id")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="silo_plan_not_found")
    row = res.data[0]
    result = row.get("result") or {}
    return {
        "status": row["status"],
        "items": result.get("items", []),
        "degraded_notes": result.get("degraded_notes", []),
        "error": row.get("error"),
    }


# ── worker handler ───────────────────────────────────────────────────────────

async def run_silo_plan_job(job: dict) -> None:
    """async_jobs handler for job_type='local_seo_silo'.

    The Fanout pipeline is blocking (synchronous DataForSEO + LLM + clustering),
    so it runs in a worker thread to keep platform-api's event loop responsive."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    keyword = (payload.get("keyword") or "").strip()
    location = (payload.get("location") or "").strip()
    location_code = payload.get("location_code")
    job_id = job["id"]
    supabase = get_supabase()

    logger.info(
        "local_seo_silo.started",
        extra={"job_id": job_id, "client_id": client_id, "keyword": keyword},
    )
    try:
        if not keyword:
            raise ValueError("keyword_required")

        plan = await asyncio.to_thread(_run_pipeline, keyword, location, location_code)
        items = _to_items(plan["per_silo"], client_id)

        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {"items": items, "degraded_notes": plan.get("degraded_notes", [])},
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
        logger.info(
            "local_seo_silo.complete",
            extra={"job_id": job_id, "client_id": client_id, "items": len(items)},
        )
    except Exception as exc:
        logger.warning(
            "local_seo_silo.failed",
            extra={"job_id": job_id, "client_id": client_id, "error": str(exc)},
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def _run_pipeline(keyword: str, location: str, location_code: Optional[int]) -> dict:
    """Blocking: silo discovery + refinement via the Fanout pipeline.

    Returns {"per_silo": [{"silo": name, "pages": [keyword, ...]}],
    "degraded_notes": [...]}. Fanout modules are imported lazily so the
    spaCy/networkx stack only loads when a plan actually runs."""
    from fanout.dataforseo import get_dataforseo
    from fanout.llm import LLMError, get_llm
    from fanout.pipeline.orchestrate import PipelineTopic, run_refinement_pipeline
    from fanout.pipeline.silo_discovery import run_silo_discovery

    # Seed discovery with "<service> <area>" so grounding + expansion are
    # geographically anchored and surface geo-modified keywords directly.
    seed = f"{keyword} {location}".strip() if location else keyword
    llm = get_llm()
    dfs = get_dataforseo(location_code or _DEFAULT_LOCATION_CODE)

    notes: list[str] = []
    disc = run_silo_discovery(
        seed=seed,
        topic_count=_TOPIC_COUNT,
        audience_hint=None,
        disambiguation_hint=None,
        llm=llm,
        dfs=dfs,
    )
    # A "<service> <city>" seed is rarely ambiguous; if it is, re-anchor on the
    # area to resolve it locally rather than dead-ending on a disambiguation gate.
    if disc.needs_disambiguation and location:
        disc = run_silo_discovery(
            seed=seed,
            topic_count=_TOPIC_COUNT,
            audience_hint=None,
            disambiguation_hint=location,
            llm=llm,
            dfs=dfs,
        )
    notes.extend(disc.degraded_notes)
    if not disc.silos:
        return {
            "per_silo": [],
            "degraded_notes": notes or ["No silos could be derived for this service / area."],
        }

    audience = disc.detected_audience or ""
    # Rationale anchor per Fanout PRD §7.1.4 (seed + rationale + audience), embedded
    # to give each silo a routing vector for the relevance gate + clustering.
    rationale_texts = [
        " ".join(part for part in (seed, s.rationale or "", audience) if part).strip()
        for s in disc.silos
    ]
    try:
        vectors = llm.embed(rationale_texts)
    except LLMError as exc:
        raise ValueError(f"embedding_failed: {exc}") from exc

    topics = [
        PipelineTopic(id=f"silo-{i}", name=s.name, embedding=vectors[i], gated=False)
        for i, s in enumerate(disc.silos)
    ]
    silo_names = {t.id: disc.silos[i].name for i, t in enumerate(topics)}

    pipe = run_refinement_pipeline(
        seed=seed,
        topics=topics,
        dfs=dfs,
        embed_fn=llm.embed,
        relevance_threshold=_RELEVANCE_THRESHOLD,
        keyword_ideas_limit=_KEYWORD_IDEAS_LIMIT,
        autocomplete_max=_AUTOCOMPLETE_MAX,
        paa_tier1_seeds=_PAA_TIER1_SEEDS,
        paa_tier2_cap=_PAA_TIER2_CAP,
        seed_terms=[seed, keyword, *disc.aliases],
        peer_terms=disc.peer_entities,
        # No language gate — geo/local-intent keywords stay (per the decision).
        language_filter=None,
    )
    notes.extend(pipe.degraded_notes)

    # Each Louvain cluster representative = one candidate page, grouped by silo.
    # If a silo had too few keywords to cluster, fall back to its strongest
    # active keywords so the silo isn't silently dropped.
    clusters = (pipe.clustering_log or {}).get("topics", {})
    per_silo: list[dict] = []
    for t in topics:
        groupings = (clusters.get(t.id) or {}).get("groupings", [])
        pages: list[str] = []
        seen: set[str] = set()
        for g in sorted(groupings, key=lambda g: g.get("size", 0), reverse=True):
            rep = (g.get("representative") or "").strip()
            key = rep.lower()
            if rep and key not in seen:
                seen.add(key)
                pages.append(rep)
            if len(pages) >= _MAX_PAGES_PER_SILO:
                break
        if not pages:
            actives = [k for k in pipe.per_topic_gated.get(t.id, []) if k.status == "active"]
            actives.sort(key=lambda k: (k.relevance_score or 0.0), reverse=True)
            for k in actives[:_MAX_PAGES_PER_SILO]:
                key = k.keyword.strip().lower()
                if key not in seen:
                    seen.add(key)
                    pages.append(k.keyword.strip())
        if pages:
            per_silo.append({"silo": silo_names[t.id], "pages": pages})

    return {"per_silo": per_silo, "degraded_notes": notes}


def _to_items(per_silo: list[dict], client_id: str) -> list[dict]:
    """Flatten silos → page targets, marking each found/missing against the
    client's already-generated `local_seo_pages` (matched on keyword)."""
    supabase = get_supabase()
    existing: dict[str, dict] = {}
    try:
        rows = (
            supabase.table("local_seo_pages")
            .select("keyword, published_doc_url")
            .eq("client_id", client_id)
            .execute()
            .data
            or []
        )
        for r in rows:
            kw = (r.get("keyword") or "").strip().lower()
            if kw:
                existing.setdefault(kw, r)
    except Exception as exc:
        logger.warning(
            "local_seo_silo.existing_lookup_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )

    items: list[dict] = []
    for group in per_silo:
        silo = group["silo"]
        for kw in group["pages"]:
            match = existing.get(kw.strip().lower())
            items.append(
                {
                    "keyword": kw,
                    "group": silo,
                    "status": "found" if match else "missing",
                    "url": (match or {}).get("published_doc_url"),
                }
            )
    return items
