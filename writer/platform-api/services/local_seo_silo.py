"""Local SEO silo planner (#2) — Fanout-powered page-target discovery.

Replaces the shallow single-keyword `/related-pages` lookup behind the
"Plan Silo" tab with the Topic Fanout keyword-research pipeline: silo discovery
(LLM grounding + DataForSEO demand / competitor signals) → keyword expansion →
relevance gating → Louvain clustering. The clustered keywords then run through a
Haiku **decision-fit** pass that organizes them into page topics by the buyer's
decision: same-intent variants (phrasing / urgency / locality) become one page's
supporting keywords, while decision-splitting modifiers (commercial vs
residential, problem type, …) get their own page. Each page topic is a candidate
local page target, grouped under its silo (and deduped across silos).

On top of the Fanout service silos, the planner adds a geocoding-verified
"Neighborhoods" silo. It proposes the target city's sub-areas (Haiku — in
whatever local term fits the country: neighborhoods, suburbs, districts), then
geocodes the city + each candidate and keeps only those whose centre falls inside
the city's geocoded footprint (`place_is_within_city`). This is country-agnostic
— it works for a US neighborhood nested in the city's locality and an AU/UK
suburb that is its own locality alike, because it verifies geography, not name
nesting — and drops adjacent towns, oversized regions, and centroid-fallback
bogus names. Best-effort and gated on the Anthropic + Google Maps keys; without
them the rest of the plan is unaffected (a degraded note explains why).

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
# Google place types too big to be a within-city sub-area. A candidate that
# geocodes to one of these (e.g. an LLM proposed a county/state) is rejected even
# if its centre happens to fall inside the city box. Everything smaller —
# locality (AU/UK suburb), sublocality, neighborhood, postal_town, etc. — is
# allowed and gated geographically instead (see `place_is_within_city`).
_TOO_BIG_TYPES = frozenset({
    "administrative_area_level_1", "administrative_area_level_2",
    "administrative_area_level_3", "country", "continent",
})


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
    # DataForSEO Labs (keyword expansion + competitor mining) only accepts a
    # COUNTRY-level location code; the city code drives degraded task errors. Pin
    # the country once at enqueue time so the worker uses it for the Labs calls
    # (the city stays in the seed/SERP).
    country_code = await locations_service.resolve_country_code(client)

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
                    "country_location_code": country_code,
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
    country_location_code = payload.get("country_location_code")
    job_id = job["id"]
    supabase = get_supabase()

    logger.info(
        "local_seo_silo.started",
        extra={"job_id": job_id, "client_id": client_id, "keyword": keyword},
    )
    try:
        if not keyword:
            raise ValueError("keyword_required")

        plan = await asyncio.to_thread(
            _run_pipeline, keyword, location, location_code, country_location_code
        )
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


def _run_pipeline(
    keyword: str, location: str, location_code: Optional[int],
    country_location_code: Optional[int] = None,
) -> dict:
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
    # DataForSEO Labs (keyword expansion + competitor mining) only accepts a
    # country-level location code — a city/region code degrades every Labs call —
    # so drive the client with the country code; the city stays in the seed. Fall
    # back to the city code, then US, only when the country can't be resolved.
    dfs = get_dataforseo(country_location_code or location_code or _DEFAULT_LOCATION_CODE)

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

    # Each silo's clustered keywords → page topics. A Haiku decision-fit pass
    # organizes them by the buyer's decision (same-intent variants become one
    # page's supporting keywords; decision-splitting modifiers get their own
    # page); absent the key or on failure we fall back to cluster representatives.
    clusters = (pipe.clustering_log or {}).get("topics", {})
    # Per-(silo, keyword) relevance, to assign a duplicate keyword to its single
    # best-fitting silo below and to rank a silo's page topics.
    rel_by_topic: dict[str, dict[str, float]] = {
        t.id: {k.keyword.strip().lower(): (k.relevance_score or 0.0)
               for k in pipe.per_topic_gated.get(t.id, [])}
        for t in topics
    }
    df_llm = _decision_fit_llm()

    raw_silos: list[dict] = []
    for t in topics:
        groupings = sorted(
            (clusters.get(t.id) or {}).get("groupings", []),
            key=lambda g: g.get("size", 0), reverse=True,
        )
        # Pool = the silo's clustered keywords (deduped); reps = the per-cluster
        # representatives, used as the decision-fit fallback.
        pool: list[str] = []
        reps: list[str] = []
        seen: set[str] = set()
        rep_seen: set[str] = set()
        for g in groupings:
            rep = (g.get("representative") or "").strip()
            if rep and rep.lower() not in rep_seen:
                rep_seen.add(rep.lower())
                reps.append(rep)
            for kw in (g.get("keywords") or ([rep] if rep else [])):
                k = (kw or "").strip()
                if k and k.lower() not in seen:
                    seen.add(k.lower())
                    pool.append(k)
        if not pool:  # too few keywords to cluster — use the strongest actives
            actives = [k for k in pipe.per_topic_gated.get(t.id, []) if k.status == "active"]
            actives.sort(key=lambda k: (k.relevance_score or 0.0), reverse=True)
            for k in actives:
                kk = k.keyword.strip()
                if kk and kk.lower() not in seen:
                    seen.add(kk.lower())
                    pool.append(kk)
                    reps.append(kk)
        pool = pool[: settings.local_seo_max_pool_per_silo]

        pages: Optional[list[dict]] = None
        if df_llm and pool:
            try:
                pages = _decision_fit_pages(keyword, _parse_area(location)[0], silo_names[t.id], pool, df_llm)
            except Exception as exc:  # noqa: BLE001 — fall back to representatives
                logger.warning(
                    "local_seo_silo.decision_fit_failed",
                    extra={"silo": silo_names[t.id], "error": str(exc)},
                )
                pages = None
        if not pages:
            pages = [{"keyword": r, "supporting_keywords": []} for r in reps]
        # Strongest page topics first, then cap.
        rel = rel_by_topic.get(t.id, {})
        pages.sort(key=lambda p: rel.get(p["keyword"].strip().lower(), 0.0), reverse=True)
        pages = pages[:_MAX_PAGES_PER_SILO]
        if pages:
            raw_silos.append({"id": t.id, "silo": silo_names[t.id], "pages": pages})

    return {"per_silo": _dedupe_across_silos(raw_silos, rel_by_topic), "degraded_notes": notes}


def _dedupe_across_silos(
    raw_silos: list[dict], rel_by_topic: dict[str, dict[str, float]],
) -> list[dict]:
    """Keep each candidate page (by its primary keyword) in only ONE silo — the
    one where it's most relevant. The relevance gate routes a generic head term
    (e.g. "plumber sydney") into several silos, so without this the same page
    target appears under each. Highest per-silo relevance wins; ties go to the
    earlier (discovery-order) silo; a silo left empty is dropped. Pure;
    unit-tested."""
    best: dict[str, tuple[float, str]] = {}  # keyword_lower -> (score, topic_id)
    for entry in raw_silos:
        rel = rel_by_topic.get(entry["id"], {})
        for page in entry["pages"]:
            key = page["keyword"].strip().lower()
            score = rel.get(key, 0.0)
            if key not in best or score > best[key][0]:
                best[key] = (score, entry["id"])

    out: list[dict] = []
    for entry in raw_silos:
        kept = [p for p in entry["pages"] if best[p["keyword"].strip().lower()][1] == entry["id"]]
        if kept:
            out.append({"silo": entry["silo"], "pages": kept})
    return out


# ── decision-fit topic mapping (page = primary keyword + same-intent variants) ─

_DECISION_FIT_SYSTEM = (
    "You are a local SEO strategist. You are given a SEED SERVICE, its CITY, and a "
    "list of candidate keywords for one silo. Do two steps.\n\n"
    "STEP 1 — SCOPE. Keep only keywords for the SAME service as the seed, targeting "
    "the CITY as a whole. DROP a keyword if it:\n"
    "  • broadens to a more generic parent service — e.g. a bare 'plumber …' when the "
    "seed is 'emergency plumber' — losing the seed's intent; or\n"
    "  • targets a specific suburb / neighbourhood / sub-area rather than the whole "
    "city (e.g. '… bondi', '… north sydney', '… eastern suburbs', '… randwick') — "
    "those are handled separately. Only the city itself is in scope as a location.\n"
    "Keep keywords that narrow the SEED service by audience (commercial vs "
    "residential), property type, problem type (gas, blocked drain, hot water, burst "
    "pipe), urgency, or phrasing.\n\n"
    "STEP 2 — GROUP the kept keywords into PAGE TOPICS by the buyer's decision. Same "
    "page when only phrasing, word order, plural, or urgency differs (e.g. 'emergency "
    "plumber sydney' = '24 hour emergency plumber in sydney'); separate page when the "
    "buyer or job changes (commercial vs residential, problem type, stage). For each "
    "page pick the primary keyword (the most natural head term) and list the "
    "same-intent keywords as supporting keywords.\n\n"
    "Use ONLY the provided keywords — never invent new ones — and put each KEPT "
    "keyword in exactly one page. Keywords you drop in step 1 simply don't appear."
)

_DECISION_FIT_SCHEMA = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "primary_keyword": {"type": "string"},
                    "supporting_keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["primary_keyword", "supporting_keywords"],
            },
        }
    },
    "required": ["pages"],
}


def _decision_fit_llm():
    """Construct the Haiku decision-fit client, or None when the Anthropic key is
    absent (the planner then falls back to cluster representatives)."""
    if not settings.anthropic_api_key:
        return None
    try:
        from fanout.llm.anthropic_client import AnthropicLLM

        return AnthropicLLM(
            api_key=settings.anthropic_api_key,
            model=settings.local_seo_decision_fit_model,
            max_tokens=2048,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; fall back to reps
        logger.warning("local_seo_silo.decision_fit_client_failed", extra={"error": str(exc)})
        return None


def _decision_fit_pages(seed_service: str, city: str, silo_name: str, keywords: list[str], llm) -> list[dict]:
    """Haiku tool-use: scope a silo's keywords to the seed service + city (dropping
    parent-service and suburb-geo terms) and organize the survivors into page
    topics by intent. Returns [{keyword, supporting_keywords}]. Validates the model
    only used the provided keywords (no invented volume) and keeps each in one
    page; keywords the model drops (off-scope) are intentionally omitted —
    suburbs are covered by the Neighborhoods silo instead."""
    allowed: dict[str, str] = {}
    for k in keywords:
        allowed.setdefault(k.strip().lower(), k.strip())
    try:
        data = llm.call_tool(
            system=_DECISION_FIT_SYSTEM,
            user=(
                f"Seed service: {seed_service}\nCity: {city}\nSilo: {silo_name}\n"
                "Keywords:\n" + "\n".join(f"- {v}" for v in allowed.values())
            ),
            tool_name="map_page_topics",
            tool_description="Scope to the seed service + city, then group into page topics by the buyer's decision.",
            input_schema=_DECISION_FIT_SCHEMA,
            purpose="local_seo_silo/decision_fit",
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 — caller falls back to cluster reps
        raise ValueError(f"decision_fit_llm_failed: {exc}") from exc

    out: list[dict] = []
    used: set[str] = set()
    for page in data.get("pages") or []:
        pk = (page.get("primary_keyword") or "").strip().lower()
        if not pk or pk not in allowed or pk in used:
            continue
        used.add(pk)
        supporting: list[str] = []
        for s in page.get("supporting_keywords") or []:
            sk = (s or "").strip().lower()
            if sk in allowed and sk != pk and sk not in used:
                used.add(sk)
                supporting.append(allowed[sk])
        out.append({"keyword": allowed[pk], "supporting_keywords": supporting})
    return out


# ── neighborhood discovery (geocoding-verified, within-city) ──────────────────

_NEIGHBORHOOD_SYSTEM = (
    "You are a local SEO expert with strong worldwide geographic knowledge. Given "
    "a place (with its state/region and country), list the real, recognized "
    "sub-areas WITHIN it that locals name — use whatever term is correct for that "
    "country: neighborhoods or districts (US), suburbs (Australia / NZ), "
    "areas/wards/boroughs (UK), barrios, quartiers, etc. Include only sub-areas "
    "inside that place's own city/metropolitan area; never separate towns or "
    "cities, counties/LGAs, regions, states, postcodes, or landmarks. If it has "
    "few recognized sub-areas, return fewer — quality over quantity. Return the "
    "local names only, with no city/country suffix."
)

_NEIGHBORHOOD_SCHEMA = {
    "type": "object",
    "properties": {
        "neighborhoods": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Local sub-area names (neighborhoods / suburbs / districts) within the place.",
        }
    },
    "required": ["neighborhoods"],
}


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


def place_is_within_city(candidate: dict, city_geo: dict) -> bool:
    """True when a forward-geocoded candidate is a real sub-area geographically
    INSIDE the target city — country-agnostic. Works for a US neighborhood
    (nested in the city's locality) and an AU/UK suburb (its own locality) alike,
    because it checks geography, not name nesting:

      1. it resolved to a place that isn't the city itself / a centroid fallback
         (distinct place_id), and
      2. it isn't a region bigger than a town (no county/state/country type), and
      3. its centre falls inside the city's geocoded footprint (bounds, padded),
         or — when the city has no footprint — within a radius of the city centre.

    Pure; unit-tested."""
    import services.maps_geocode as mg

    if not candidate or not candidate.get("matched"):
        return False
    if not city_geo or not city_geo.get("matched"):
        return False
    cpid, citypid = candidate.get("place_id"), city_geo.get("place_id")
    if cpid and citypid and cpid == citypid:
        return False  # snapped to the city itself — a bogus / centroid-fallback name
    types = {str(t).lower() for t in (candidate.get("result_types") or [])}
    if types & _TOO_BIG_TYPES:
        return False  # a county / state / country, not a sub-area
    lat, lng = candidate.get("lat"), candidate.get("lng")
    if lat is None or lng is None:
        return False
    bounds = city_geo.get("bounds")
    if bounds:
        return mg.point_in_bounds(lat, lng, bounds, pad=settings.local_seo_city_bounds_pad)
    clat, clng = city_geo.get("lat"), city_geo.get("lng")
    if clat is None or clng is None:
        return False
    return mg.haversine_km(lat, lng, clat, clng) <= settings.local_seo_neighborhood_radius_km


def _propose_neighborhoods(city: str, state: str, country: str, max_n: int) -> list[str]:
    """Haiku tool-use: candidate sub-areas within the place, in whatever local term
    fits the country (neighborhood / suburb / district). Geocoding verifies them
    downstream, so a rough list is fine. Blocking — call via a thread."""
    from fanout.llm.anthropic_client import AnthropicError, AnthropicLLM

    llm = AnthropicLLM(
        api_key=settings.anthropic_api_key,
        model=settings.local_seo_neighborhood_model,
        max_tokens=1024,
    )
    where = ", ".join(p for p in (city, state, country) if p)
    try:
        data = llm.call_tool(
            system=_NEIGHBORHOOD_SYSTEM,
            user=(
                f"Place: {where}. List up to {max_n} distinct sub-areas (neighborhoods, "
                "suburbs, or districts — whatever locals call them) located inside this "
                "place's own city/metro area."
            ),
            tool_name="list_neighborhoods",
            tool_description="Return local sub-areas located within the given place.",
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
    """Propose sub-areas of the target city, geocode-verify each falls inside the
    city's footprint, and return a "Neighborhoods" silo of "<service> <sub-area>"
    page targets (deduped against the silos already planned). Country-agnostic and
    best-effort: any failure or missing prerequisite yields no silo + a degraded
    note, never an aborted plan."""
    city, state, country = _parse_area(location)
    if not city:
        return None, ["Neighborhood pages skipped — no city in the area."]
    if not settings.anthropic_api_key:
        return None, ["Neighborhood pages skipped — content model not configured."]
    if not settings.google_maps_api_key:
        return None, [
            "Neighborhood pages skipped — geocoding not configured, so sub-areas "
            "can't be verified as within the city."
        ]

    try:
        names = await asyncio.to_thread(
            _propose_neighborhoods, city, state, country, settings.local_seo_max_neighborhoods
        )
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_propose_failed", extra={"error": str(exc)})
        return None, ["Neighborhood pages skipped — could not list sub-areas."]
    if not names:
        return None, []

    from services import maps_geocode

    def _query(*parts: str) -> str:
        return ", ".join(p for p in parts if p)

    # Geocode the city itself (for its footprint) alongside the candidates, in one
    # cached batch.
    city_query = _query(city, state, country)
    queries = {name: _query(name, city, state, country) for name in names}
    try:
        geo = await maps_geocode.forward_geocode_places(
            [city_query, *queries.values()], supabase=supabase
        )
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_geocode_failed", extra={"error": str(exc)})
        return None, ["Neighborhood pages skipped — geocoding lookup failed."]

    city_geo = geo.get(city_query) or {}
    if not city_geo.get("matched") or (not city_geo.get("bounds") and city_geo.get("lat") is None):
        return None, ["Neighborhood pages skipped — couldn't resolve the city to verify sub-areas."]

    # Keywords already planned in other silos — don't re-surface a sub-area page
    # the Fanout expansion already produced.
    existing = {p["keyword"].strip().lower() for g in per_silo for p in g.get("pages", [])}
    pages: list[dict] = []
    seen: set[str] = set()
    for name in names:
        if not place_is_within_city(geo.get(queries[name]) or {}, city_geo):
            continue
        page_kw = f"{keyword} {name}".strip()
        key = page_kw.lower()
        if key not in existing and key not in seen:
            seen.add(key)
            pages.append({"keyword": page_kw, "supporting_keywords": []})

    if not pages:
        return None, ["No sub-areas could be verified within the city."]
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
        for page in group["pages"]:
            kw = page["keyword"]
            match = existing.get(kw.strip().lower())
            items.append(
                {
                    "keyword": kw,
                    "group": silo,
                    "status": "found" if match else "missing",
                    "url": (match or {}).get("published_doc_url"),
                    "supporting_keywords": page.get("supporting_keywords", []),
                }
            )
    return items
