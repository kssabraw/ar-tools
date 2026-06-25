"""Service-page planner — Fanout-powered "what service pages should this business
have?" discovery.

A completeness engine for the **service_page** content type: rather than the team
guessing which service pages to create, this seeds the Topic Fanout keyword-research
pipeline with the client's **business category** (its GBP category, enriched with any
services scraped from the site) and surfaces the full set of candidate service pages,
grouped by silo. Each candidate is marked found (a service_page run already exists) vs
missing, so the team can bulk-create the gaps via `POST /runs/bulk`.

It mirrors `services/local_seo_silo.py` (same Fanout pipeline, by import) with three
deliberate differences for service pages:
  - **Seed = business category**, not a single "<service> <area>" keyword — so the
    plan reflects the whole business even when the site is thin or missing service
    pages entirely (the exact gap this solves).
  - **National / non-geo** — candidates are plain service targets ("drain cleaning");
    geography is the location-page module's job, so there is no area anchor and no
    "Neighborhoods" silo.
  - **Found/missing is computed against `runs` (content_type='service_page')**, not
    `local_seo_pages`.

The Fanout pipeline bills DataForSEO/LLM and runs for minutes, so it executes as an
`async_jobs` job (job_type='service_page_plan'); the route enqueues + polls.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Tuning for the service-page use of the Fanout pipeline. A touch broader than the
# local-silo planner (services fan out wider than a single geo service) but bounded
# so the bulk-create list stays usable. The relevance threshold sits between the
# local planner's relaxed 0.50 (kept geo variants) and Fanout's strict 0.62 — these
# are non-geo service terms, so we can be a bit tighter than local without cutting
# legitimate sub-services.
_TOPIC_COUNT = 6
_RELEVANCE_THRESHOLD = 0.58
_KEYWORD_IDEAS_LIMIT = 300
_AUTOCOMPLETE_MAX = 300
_PAA_TIER1_SEEDS = 6
_PAA_TIER2_CAP = 24
_MAX_PAGES_PER_SILO = 10
# National US market for demand signals (candidates themselves are non-geo).
_DEFAULT_LOCATION_CODE = 2840
# How many scraped services to carry as relevance-anchor terms.
_MAX_SEED_TERMS = 10


def _get_client(client_id: str) -> dict:
    supabase = get_supabase()
    res = supabase.table("clients").select("*").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data


def _scraped_services(client: dict) -> list[str]:
    wa = client.get("website_analysis") or {}
    out: list[str] = []
    seen: set[str] = set()
    for s in (wa.get("services") or []):
        name = (s or "").strip() if isinstance(s, str) else ""
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def derive_seed(client: dict) -> tuple[str, list[str], list[str]]:
    """Resolve the discovery seed + relevance-anchor terms + degraded notes.

    Primary seed is the GBP category (most authoritative "what business is this");
    scraped services become anchor terms. Falls back to the scraped services, then
    the business name, so a client with a thin/absent site still gets a plan. Pure;
    unit-tested."""
    notes: list[str] = []
    gbp = client.get("gbp") or {}
    category = (gbp.get("gbp_category") or "").strip()
    services = _scraped_services(client)
    name = (client.get("name") or "").strip()

    if category:
        return category, services[:_MAX_SEED_TERMS], notes
    if services:
        notes.append("No GBP category — seeded discovery from the site's services.")
        return services[0], services[1 : _MAX_SEED_TERMS + 1], notes
    if name:
        notes.append("No GBP category or scraped services — seeded from the business name.")
        return f"{name} services", [], notes
    return "", [], notes


async def start_service_plan(client_id: str, user_id: str) -> str:
    """Enqueue a `service_page_plan` job. Returns the job id. One plan in flight per
    client — a pending/running job is reused rather than stacking another run."""
    _get_client(client_id)  # validate existence/ownership

    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "service_page_plan")
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
                "job_type": "service_page_plan",
                "entity_id": client_id,
                "payload": {"client_id": client_id, "user_id": user_id},
            }
        )
        .execute()
    )
    return res.data[0]["id"]


def get_service_plan(job_id: str, client_id: str) -> dict:
    """Read a plan job's row. Returns {status, items, degraded_notes, error}. Scoped
    to the client (the job's entity_id) so a job id can't be polled across clients."""
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .select("status, result, error, entity_id")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="service_plan_not_found")
    row = res.data[0]
    result = row.get("result") or {}
    return {
        "status": row["status"],
        "items": result.get("items", []),
        "degraded_notes": result.get("degraded_notes", []),
        "error": row.get("error"),
    }


# ── worker handler ───────────────────────────────────────────────────────────

async def run_service_plan_job(job: dict) -> None:
    """async_jobs handler for job_type='service_page_plan'. The Fanout pipeline is
    blocking, so it runs in a worker thread to keep the event loop responsive."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()

    logger.info("service_page_plan.started", extra={"job_id": job_id, "client_id": client_id})
    try:
        client = _get_client(client_id)
        seed, seed_terms, notes = derive_seed(client)
        if not seed:
            raise ValueError("no_seed: client has no GBP category, scraped services, or name")

        plan = await asyncio.to_thread(_run_pipeline, seed, seed_terms)
        plan["degraded_notes"] = [*notes, *plan.get("degraded_notes", [])]
        items = _to_items(plan["per_silo"], client_id)

        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {"items": items, "degraded_notes": plan.get("degraded_notes", [])},
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
        logger.info(
            "service_page_plan.complete",
            extra={"job_id": job_id, "client_id": client_id, "items": len(items)},
        )
    except Exception as exc:
        logger.warning(
            "service_page_plan.failed",
            extra={"job_id": job_id, "client_id": client_id, "error": str(exc)},
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def _run_pipeline(seed: str, seed_terms: list[str]) -> dict:
    """Blocking: silo discovery + refinement via the Fanout pipeline, seeded by the
    business category. Returns {"per_silo": [{"silo": name, "pages": [kw, ...]}],
    "degraded_notes": [...]}. Fanout modules are imported lazily so the spaCy/networkx
    stack only loads when a plan actually runs."""
    from fanout.dataforseo import get_dataforseo
    from fanout.llm import LLMError, get_llm
    from fanout.pipeline.orchestrate import PipelineTopic, run_refinement_pipeline
    from fanout.pipeline.silo_discovery import run_silo_discovery

    llm = get_llm()
    dfs = get_dataforseo(_DEFAULT_LOCATION_CODE)

    notes: list[str] = []
    disc = run_silo_discovery(
        seed=seed,
        topic_count=_TOPIC_COUNT,
        audience_hint=None,
        disambiguation_hint=None,
        llm=llm,
        dfs=dfs,
    )
    notes.extend(disc.degraded_notes)
    if not disc.silos:
        return {
            "per_silo": [],
            "degraded_notes": notes or ["No service silos could be derived for this business."],
        }

    audience = disc.detected_audience or ""
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
        seed_terms=[seed, *seed_terms, *disc.aliases],
        peer_terms=disc.peer_entities,
        language_filter=None,
    )
    notes.extend(pipe.degraded_notes)

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
    """Flatten silos → page targets, marking each found/missing against the client's
    already-created `service_page` runs (matched on the run's keyword OR service)."""
    supabase = get_supabase()
    existing: set[str] = set()
    try:
        rows = (
            supabase.table("runs")
            .select("keyword, service")
            .eq("client_id", client_id)
            .eq("content_type", "service_page")
            .execute()
            .data
            or []
        )
        for r in rows:
            for value in (r.get("keyword"), r.get("service")):
                norm = (value or "").strip().lower()
                if norm:
                    existing.add(norm)
    except Exception as exc:
        logger.warning(
            "service_page_plan.existing_lookup_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )

    items: list[dict] = []
    for group in per_silo:
        silo = group["silo"]
        for kw in group["pages"]:
            found = kw.strip().lower() in existing
            items.append(
                {
                    "keyword": kw,
                    "group": silo,
                    "status": "found" if found else "missing",
                    "url": None,
                }
            )
    return items
