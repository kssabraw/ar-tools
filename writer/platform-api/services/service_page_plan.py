"""Service-page planner — Fanout-powered "what service pages should this business
have?" discovery.

A completeness engine for the **service_page** content type: rather than the team
guessing which service pages to create, this seeds the Topic Fanout keyword-research
pipeline with the client's **business category** (its GBP category, enriched with any
services scraped from the site) and surfaces the full set of candidate service pages,
grouped by silo. Each candidate is marked found (a service_page run already exists) vs
missing, so the team can bulk-create the gaps via `POST /runs/bulk`.

After discovery, candidates the client **already publishes** are removed: the planner
reads the live site's sitemap (`services/sitemap.py`) and drops any candidate whose
slug already exists on the site, so the plan only ever surfaces genuine gaps. The
check is best-effort — if the sitemap can't be read the full list is kept with a
degraded note.

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
import re
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import dataforseo_rank
from services.sitemap import fetch_sitemap_urls

logger = logging.getLogger(__name__)

# Sentinel rank: the DataForSEO check couldn't run (error or not configured), as
# distinct from None (ran, domain not in the SERP → genuinely not ranking).
_RANK_UNKNOWN = -1

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

# Tokens stripped before matching a candidate keyword against a site's URL slugs —
# connectors plus the generic "service(s)" wrapper that shows up as a sitemap
# directory (`/services/...`) rather than a distinguishing term.
_MATCH_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "of", "in", "on", "to", "your", "our",
    "near", "me", "service", "services", "page", "pages", "index", "html", "htm",
    "php", "aspx",
}

# A path segment from this set marks a URL as non-service content — a blog post,
# taxonomy/archive, store, account, or legal page. Such pages *mention* services
# without being the service's landing page, so they must never suppress a candidate
# (e.g. `/blog/signs-you-need-drain-cleaning/` is not the "drain cleaning" page).
_NON_SERVICE_SEGMENTS = {
    "blog", "blogs", "post", "posts", "article", "articles", "news", "story",
    "stories", "tag", "tags", "category", "categories", "topic", "topics",
    "author", "authors", "product", "products", "shop", "store", "cart",
    "checkout", "account", "feed", "rss", "search", "privacy", "terms",
    "cookie", "cookies", "sitemap", "wp-content", "wp-json", "wp-admin", "page",
}


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

        # Reconcile candidates against the client's live site: match discovered
        # pages to the sitemap, then rank-check each match. A page ranking in the top
        # N for its keyword is dropped (the site already covers it); one ranking
        # worse (or not at all) is surfaced for reoptimization instead.
        website_url = (client.get("website_url") or "").strip()
        if website_url and items:
            site_urls = await fetch_sitemap_urls(website_url)
            if site_urls:
                kept, on_site = filter_existing_on_site(items, site_urls)
                reopt_items, rank_notes = await _rank_classify_on_site(on_site, client)
                items = kept + reopt_items
                plan["degraded_notes"].extend(rank_notes)
                logger.info(
                    "service_page_plan.site_filter",
                    extra={
                        "job_id": job_id,
                        "client_id": client_id,
                        "site_urls": len(site_urls),
                        "on_site": len(on_site),
                        "reoptimize": len(reopt_items),
                    },
                )
            else:
                plan["degraded_notes"].append(
                    "Could not read the site's sitemap — skipped the on-site duplicate check."
                )

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


# ── on-site duplicate removal (sitemap match) ─────────────────────────────────

def _content_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens with stopwords (and 1-char noise) dropped."""
    return {
        tok
        for tok in re.split(r"[^a-z0-9]+", (text or "").lower())
        if len(tok) > 1 and tok not in _MATCH_STOPWORDS
    }


def _page_slug_tokens(url: str) -> set[str] | None:
    """Content tokens of a URL's **final path segment** (its page slug), or None when
    the URL is non-service content (blog/taxonomy/store/…) or has no usable slug.

    Only the last segment is considered, so parent directories like `/services/` and
    unrelated words elsewhere in the path can't trigger a match — a blog post at
    `/blog/...-drain-cleaning/` is excluded outright by its `blog` segment."""
    path = unquote(urlsplit(url or "").path)
    segments = [seg for seg in path.split("/") if seg]
    if not segments:
        return None
    if any(seg.lower() in _NON_SERVICE_SEGMENTS for seg in segments):
        return None
    tokens = _content_tokens(segments[-1])
    return tokens or None


def _build_url_index(site_urls: list[str]) -> list[tuple[str, set[str]]]:
    """Pre-tokenize site URLs once (final-segment slugs only) so matching is
    O(candidates × urls) on sets. Non-service / slug-less URLs are dropped."""
    index: list[tuple[str, set[str]]] = []
    for url in site_urls:
        toks = _page_slug_tokens(url)
        if toks:
            index.append((url, toks))
    return index


def _match_existing_url(keyword: str, url_index: list[tuple[str, set[str]]]) -> str | None:
    """Return a live URL whose page slug is the *same* service as `keyword`, else
    None. Matching is exact token-set equality against the final path segment, which
    keeps qualifiers honest in both directions — "drain cleaning" won't match
    "/emergency-drain-cleaning/" (the page is more specific) and "plumbing" won't
    match "/commercial-plumbing/" (a narrower variant). Stopwords ("services", "the",
    …) are ignored, so "/drain-cleaning-services/" still equals "drain cleaning".
    Erring toward keeping a candidate (a missed match just re-surfaces a real page)
    is the safe direction for a gap finder."""
    kw_tokens = _content_tokens(keyword)
    if not kw_tokens:
        return None
    for url, toks in url_index:
        if kw_tokens == toks:
            return url
    return None


def filter_existing_on_site(
    items: list[dict], site_urls: list[str]
) -> tuple[list[dict], list[dict]]:
    """Split planner items into (kept, on_site) by matching each against the site's
    published URLs. `on_site` items (the candidate already exists on the live site,
    `url` set to the match) are then rank-checked by the caller — ranking well →
    dropped, ranking poorly → offered for reoptimization. Pure; unit-tested."""
    url_index = _build_url_index(site_urls)
    kept: list[dict] = []
    on_site: list[dict] = []
    for item in items:
        match = _match_existing_url(item.get("keyword", ""), url_index)
        if match:
            on_site.append({**item, "url": match})
        else:
            kept.append(item)
    return kept, on_site


def classify_on_site(
    on_site: list[dict], ranks: list[int | None], top_n: int
) -> tuple[list[dict], int, int]:
    """Pure: split on-site matches by their domain's SERP rank. Returns
    (reoptimize_items, removed_top_n, unchecked).

    - rank within `top_n` → dropped (the site already ranks well for it).
    - rank worse than `top_n`, or None (ran but not in the SERP) → a
      status='reoptimize' item carrying its `url` + `rank` (None = not ranking).
    - `_RANK_UNKNOWN` (the check couldn't run) → dropped + counted; we won't claim a
      page underperforms when we couldn't measure it.

    `ranks` is positional with `on_site`."""
    reoptimize: list[dict] = []
    removed_top = 0
    unchecked = 0
    for item, rank in zip(on_site, ranks):
        if rank == _RANK_UNKNOWN:
            unchecked += 1
            continue
        if rank is not None and rank <= top_n:
            removed_top += 1
            continue
        reoptimize.append({**item, "status": "reoptimize", "rank": rank})
    return reoptimize, removed_top, unchecked


async def _safe_rank(keyword: str, domain: str, location_code: int) -> int | None:
    """fetch_serp_rank, mapping any failure to the `_RANK_UNKNOWN` sentinel."""
    try:
        return await dataforseo_rank.fetch_serp_rank(keyword, domain, location_code)
    except Exception as exc:
        logger.warning(
            "service_page_plan.rank_check_failed",
            extra={"keyword": keyword, "error": str(exc)},
        )
        return _RANK_UNKNOWN


async def _rank_classify_on_site(
    on_site: list[dict], client: dict
) -> tuple[list[dict], list[str]]:
    """Rank-check on-site matches (bounded + concurrent) and classify them into
    reoptimize candidates vs dropped. Returns (reoptimize_items, degraded_notes)."""
    notes: list[str] = []
    if not on_site:
        return [], notes

    top_n = settings.service_page_rank_top_n
    if not (settings.dataforseo_login and settings.dataforseo_password):
        notes.append(
            f"Removed {len(on_site)} already-published page(s); DataForSEO isn't "
            f"configured, so no top-{top_n} rank check ran."
        )
        return [], notes

    domain = dataforseo_rank.extract_domain(client.get("website_url") or "")
    location_code = dataforseo_rank.location_code_for(client)
    cap = settings.service_page_plan_max_rank_checks
    to_check, over_cap = on_site[:cap], on_site[cap:]

    ranks = await asyncio.gather(
        *(_safe_rank(it["keyword"], domain, location_code) for it in to_check)
    )
    reoptimize, removed_top, unchecked = classify_on_site(to_check, ranks, top_n)

    if removed_top:
        notes.append(f"Removed {removed_top} already-published page(s) ranking in the top {top_n}.")
    if reoptimize:
        notes.append(
            f"{len(reoptimize)} already-published page(s) aren't ranking top {top_n} — "
            "offered for reoptimization."
        )
    if unchecked:
        notes.append(f"{unchecked} already-published page(s) couldn't be rank-checked and were removed.")
    if over_cap:
        notes.append(
            f"Rank check capped at {cap}; {len(over_cap)} more already-published "
            "page(s) were removed unchecked."
        )
    return reoptimize, notes
