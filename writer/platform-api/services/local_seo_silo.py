"""Local SEO silo planner (#2) — Fanout-powered page-target discovery.

Replaces the shallow single-keyword `/related-pages` lookup behind the
"Plan Silo" tab with the Topic Fanout keyword-research pipeline: silo discovery
(LLM grounding + DataForSEO demand / competitor signals) → keyword expansion →
relevance gating → Louvain clustering. Each cluster representative becomes one
candidate local page target, grouped under its silo.

On top of the Fanout service silos, the planner adds a geocoding-verified
"Neighborhoods" silo: it proposes neighborhoods within the target city (Haiku),
then forward-geocodes each (`services/maps_geocode.forward_geocode_places`) and
keeps only those that resolve to a neighborhood-level place inside that city —
adjacent towns and bogus names are dropped — offering "<service> <neighborhood>"
page targets. It's best-effort and gated on the Anthropic + Google Maps keys;
without them the rest of the plan is unaffected (a degraded note explains why).

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

from config import settings
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

# Neighborhood discovery. The seed service is paired with each verified
# neighborhood ("<service> <neighborhood>") as a page target under this silo.
_NEIGHBORHOOD_SILO = "Neighborhoods"
# Google place types that mark a result as a real sub-city locality. A bogus or
# unknown name falls back to the city centroid (types {"locality", ...}), which
# is excluded — so only genuine neighborhoods survive verification.
_NEIGHBORHOOD_TYPES = frozenset(
    {"neighborhood", "sublocality", "sublocality_level_1", "sublocality_level_2"}
)


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
        # Append a geocoding-verified "Neighborhoods" silo (within-city only). It's
        # an additive best-effort step, so a defensive failure here must never sink
        # an otherwise-good plan — belt-and-suspenders around its own internal
        # guards.
        try:
            neigh_entry, neigh_notes = await _discover_neighborhood_silo(
                keyword, location, plan["per_silo"], supabase
            )
        except Exception as exc:  # noqa: BLE001 — neighborhoods are non-critical
            logger.warning(
                "local_seo_silo.neighborhoods_unexpected_error",
                extra={"job_id": job_id, "client_id": client_id, "error": str(exc)},
            )
            neigh_entry, neigh_notes = None, ["Neighborhood pages skipped — unexpected error."]
        if neigh_entry:
            plan["per_silo"].append(neigh_entry)
        plan["degraded_notes"] = [*plan.get("degraded_notes", []), *neigh_notes]
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


# ── neighborhood discovery (geocoding-verified, within-city) ──────────────────

_NEIGHBORHOOD_SYSTEM = (
    "You are a local SEO expert with deep US geographic knowledge. Given a city, "
    "list real, recognized neighborhoods, districts, or named communities located "
    "STRICTLY WITHIN that city's municipal limits. Never include separate "
    "incorporated cities, suburbs, counties, regions, ZIP codes, or landmarks. If "
    "the city has few recognized neighborhoods, return fewer — quality over "
    "quantity. Return names only, as locals would say them (no city suffix)."
)

_NEIGHBORHOOD_SCHEMA = {
    "type": "object",
    "properties": {
        "neighborhoods": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Neighborhood / district names within the city.",
        }
    },
    "required": ["neighborhoods"],
}


def _norm(value: Optional[str]) -> str:
    return " ".join((value or "").lower().split())


def _parse_area(location: str) -> tuple[str, str, str]:
    """Split a DataForSEO canonical area into (city, state, country). The US
    canonical is "City,State,Country" (3 segments); a 2-segment area is
    "City,Country" (e.g. "London,United Kingdom"), so the second segment is the
    country — not a state. Degrades gracefully for a bare city."""
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    city = parts[0] if parts else ""
    if len(parts) >= 3:
        state, country = parts[1], parts[-1]
    elif len(parts) == 2:
        state, country = "", parts[1]
    else:
        state, country = "", ""
    return city, state, country


def neighborhood_is_in_city(parsed: dict, target_city: str) -> bool:
    """True when a forward-geocode result is a neighborhood-level place whose city
    matches the target — the gate that drops adjacent towns and city-centroid
    fallbacks. Pure; unit-tested."""
    if not parsed or not parsed.get("matched"):
        return False
    if not target_city or _norm(parsed.get("city")) != _norm(target_city):
        return False
    types = {str(t).lower() for t in (parsed.get("result_types") or [])}
    return bool(types & _NEIGHBORHOOD_TYPES)


def _propose_neighborhoods(city: str, state: str, max_n: int) -> list[str]:
    """Haiku tool-use: candidate neighborhoods within the city (geocoding verifies
    them downstream, so a rough list is fine). Blocking — call via a thread."""
    from fanout.llm.anthropic_client import AnthropicError, AnthropicLLM

    llm = AnthropicLLM(
        api_key=settings.anthropic_api_key,
        model=settings.local_seo_neighborhood_model,
        max_tokens=1024,
    )
    where = f"{city}, {state}".strip(", ") if state else city
    try:
        data = llm.call_tool(
            system=_NEIGHBORHOOD_SYSTEM,
            user=(
                f"City: {where}. List up to {max_n} distinct neighborhoods, districts, "
                "or named communities located strictly within this city's limits."
            ),
            tool_name="list_neighborhoods",
            tool_description="Return neighborhoods located within the given city.",
            input_schema=_NEIGHBORHOOD_SCHEMA,
            purpose="local_seo_silo/neighborhoods",
            temperature=0.0,
        )
    except AnthropicError as exc:
        raise ValueError(f"neighborhood_llm_failed: {exc}") from exc

    seen: set[str] = set()
    names: list[str] = []
    for raw in data.get("neighborhoods") or []:
        name = (raw or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names[:max_n]


async def _discover_neighborhood_silo(
    keyword: str, location: str, per_silo: list[dict], supabase,
) -> tuple[Optional[dict], list[str]]:
    """Propose neighborhoods within the area's city, forward-geocode-verify each is
    inside that city, and return a "Neighborhoods" silo of "<service> <neighborhood>"
    page targets (deduped against the silos already planned). Best-effort: any
    failure or missing prerequisite yields no silo + a degraded note, never an
    aborted plan."""
    city, state, country = _parse_area(location)
    if not city:
        return None, ["Neighborhood pages skipped — no city in the area."]
    if not settings.anthropic_api_key:
        return None, ["Neighborhood pages skipped — content model not configured."]
    if not settings.google_maps_api_key:
        return None, [
            "Neighborhood pages skipped — geocoding not configured, so neighborhoods "
            "can't be verified as within the city."
        ]

    try:
        names = await asyncio.to_thread(
            _propose_neighborhoods, city, state, settings.local_seo_max_neighborhoods
        )
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_propose_failed", extra={"error": str(exc)})
        return None, ["Neighborhood pages skipped — could not list neighborhoods."]
    if not names:
        return None, []

    from services import maps_geocode

    def _query(name: str) -> str:
        return ", ".join(p for p in (name, city, state, country) if p)

    queries = {name: _query(name) for name in names}
    try:
        geo = await maps_geocode.forward_geocode_places(
            list(queries.values()), supabase=supabase
        )
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_geocode_failed", extra={"error": str(exc)})
        return None, ["Neighborhood pages skipped — geocoding lookup failed."]

    # Keywords already planned in other silos — don't re-surface a neighborhood
    # page the Fanout expansion already produced.
    existing = {p.strip().lower() for g in per_silo for p in g.get("pages", [])}
    pages: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not neighborhood_is_in_city(geo.get(queries[name]) or {}, city):
            continue
        page = f"{keyword} {name}".strip()
        key = page.lower()
        if key not in existing and key not in seen:
            seen.add(key)
            pages.append(page)

    if not pages:
        return None, ["No neighborhoods could be verified within the city."]
    return {"silo": _NEIGHBORHOOD_SILO, "pages": pages}, []


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
