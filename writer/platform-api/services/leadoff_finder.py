"""LeadOff city-finder — "which cities should I target for category X?"

Two paths, one entry point:

  * **Board lookup (free, instant)** — for a category already in the scan
    (94 categories × 1,476 cities): filter the graded board to that category,
    optionally by state, and rank. $0 — the scan is already paid for.
  * **City-finder (paid, async)** — for a NEW category not in the scan
    (e.g. "computer support and services"): the demographic scaffolding
    (cities + populations) is already owned, so we only pay for the two
    category-specific unknowns — this keyword's demand + who currently ranks —
    and only across a population-ranked shortlist, not all 4,682 cities. Runs
    the tryout's per-market machinery (Google Ads volume + Maps SERP at 13z +
    the same economics/grade), transposed to one category × N cities. Typ.
    ~$0.06/city → ~$6–10 for a 100–150 city shortlist. Budget-guarded.

Both rank by the same demand × winnability sabermetrics as the board, so the
answer is comparable whether the category was pre-scanned or freshly found.
Surfaced via the API and the SerMastr assistant (board lookup = a free inline
tool; the paid finder = a confirm-gated action).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# City-finder cost model (per candidate city): one Google Ads volume task +
# one Maps SERP. Mirrors the tryout's per-call costs.
COST_FINDER_PER_CITY = 0.06
DEFAULT_SHORTLIST = 120       # population-ranked candidates for a paid finder
MAX_SHORTLIST = 300


# ── Category resolution (pure) ────────────────────────────────────────────────

_CAT_STOP = {"service", "services", "company", "contractor", "and", "the",
             "shop", "store", "business", "near", "me", "a", "for"}


def _stem(t: str) -> str:
    """Light suffix strip so verb/noun forms of a trade collapse together
    (plumbing↔plumber→plumb, roofing↔roofer→roof, electrician→electric).
    Conservative: only trims when ≥4 chars remain."""
    for suf in ("ing", "ians", "ian", "ers", "er", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            return t[: -len(suf)]
    return t


def _tokens(s: str) -> set[str]:
    return {_stem(t) for t in re.findall(r"[a-z]+", (s or "").lower())
            if t not in _CAT_STOP and len(t) >= 3}


def resolve_category(text: str, board_categories: list[str]) -> Optional[str]:
    """Best board-category match for a free-text category, or None when nothing
    overlaps. Pure. Exact (normalized) match wins; else the category sharing the
    most meaningful tokens (must share ≥1)."""
    want = _tokens(text)
    if not want:
        return None
    norm = re.sub(r"[^a-z ]", " ", (text or "").lower()).strip()
    best, best_score = None, 0
    for cat in board_categories:
        ctoks = _tokens(cat)
        if re.sub(r"[^a-z ]", " ", cat.lower()).strip() == norm:
            return cat
        overlap = len(want & ctoks)
        # prefer the tightest match (high overlap, few extra tokens)
        score = overlap * 10 - abs(len(ctoks) - len(want))
        if overlap and score > best_score:
            best, best_score = cat, score
    return best


# ── Board lookup (Part A — free) ──────────────────────────────────────────────

def board_categories() -> list[str]:
    from services.leadoff_db import get_leadoff_client
    rows = (get_leadoff_client().table("leadoff_board")
            .select("category").execute().data or [])
    return sorted({r["category"] for r in rows if r.get("category")})


def find_board_cities(category: str, *, state: Optional[str] = None,
                      sort: str = "build", limit: int = 15) -> dict[str, Any]:
    """Ranked board cities for an already-scanned category (enriched grades).
    Reuses list_board so the grades carry the permit/proximity enrichment."""
    from services import leadoff as svc
    from services.leadoff import BOARD_SORTS, DEFAULT_CAPTURE, DEFAULT_TIER

    if sort not in BOARD_SORTS:
        sort = "build"
    res = svc.list_board(city=None, state=(state.upper() if state else None),
                         category=category, min_demand=None, sort=sort,
                         capture=DEFAULT_CAPTURE, lead_tier=DEFAULT_TIER,
                         limit=limit, prefetch=max(limit, 200))
    return {"category": category, "state": state, "sort": sort,
            "markets": res["markets"], "as_of": res.get("as_of")}


# ── City-finder (Part B — paid) ───────────────────────────────────────────────

def _client():
    from services.leadoff_db import get_leadoff_client
    return get_leadoff_client()


def shortlist_cities(*, state: Optional[str], region: Optional[str],
                     min_pop: int, limit: int) -> list[dict[str, Any]]:
    """Population-ranked candidate cities for a paid finder (cheap: our own
    cities table). A location_code is required (Google Ads volume needs it)."""
    q = (_client().table("cities")
         .select("city_id, name, state_code, region, population, "
                 "latitude, longitude, location_code")
         .not_.is_("location_code", "null")
         .gte("population", min_pop))
    if state:
        q = q.eq("state_code", state.upper())
    if region:
        q = q.eq("region", region)
    rows = (q.order("population", desc=True).limit(min(limit, MAX_SHORTLIST))
            .execute().data or [])
    return rows


def estimate_finder_cost(n_cities: int) -> float:
    return round(n_cities * COST_FINDER_PER_CITY, 2)


def enqueue_city_finder(user_id: str, *, category: str, state: Optional[str],
                        region: Optional[str], min_pop: int, limit: int,
                        lead_value: Optional[float], est_cost: float) -> dict[str, Any]:
    from db.supabase_client import get_supabase
    run = get_supabase().table("leadoff_city_finder_runs").insert({
        "requested_by": user_id, "category": category, "state": state,
        "region": region, "status": "pending", "est_cost": est_cost,
    }).execute().data[0]
    job = get_supabase().table("async_jobs").insert({
        "job_type": "leadoff_city_finder", "entity_id": run["id"],
        "payload": {"run_id": run["id"], "category": category, "state": state,
                    "region": region, "min_pop": min_pop, "limit": limit,
                    "lead_value": lead_value, "user_id": user_id,
                    "est_cost": est_cost}}).execute().data[0]
    return {"run_id": run["id"], "job_id": job["id"], "est_cost": est_cost}


async def run_city_finder_job(job: dict) -> None:
    """One category × N shortlisted cities: volume + Maps SERP + score. Reuses
    the tryout machinery (transposed). Writes ranked results to the run row."""
    import asyncio

    import httpx

    from db.supabase_client import get_supabase
    from services import leadoff as svc
    from services import leadoff_actions as la
    from services.leadoff import DEFAULT_CAPTURE

    supabase = get_supabase()
    payload = job.get("payload") or {}
    run_id = payload["run_id"]
    category = payload["category"]

    def _fail(err: str) -> None:
        supabase.table("leadoff_city_finder_runs").update(
            {"status": "failed", "error": err[:500], "completed_at": "now()"}
        ).eq("id", run_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": err[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()

    try:
        supabase.table("leadoff_city_finder_runs").update({"status": "running"}) \
            .eq("id", run_id).execute()
        cities = shortlist_cities(state=payload.get("state"),
                                  region=payload.get("region"),
                                  min_pop=int(payload.get("min_pop") or 30000),
                                  limit=int(payload.get("limit") or DEFAULT_SHORTLIST))
        if not cities:
            _fail("no_candidate_cities")
            return
        # lead value: the category's CPL if we have it, else the caller's
        # override, else a flagged default (CPL is user-supplied per category).
        cpl_map = la._lead_values("mid")
        lead_value = (cpl_map.get(category) or payload.get("lead_value")
                      or svc._client().table("lead_values")
                      .select("cpl_mid").ilike("category_name", category)
                      .limit(1).execute().data)
        if isinstance(lead_value, list):
            lead_value = lead_value[0]["cpl_mid"] if lead_value else None
        lead_value = float(lead_value) if lead_value else float(
            __import__("config").settings.leadoff_finder_default_lead_value)
        breakpoints = la._breakpoints()
        keyword = category
        sem = asyncio.Semaphore(12)
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient() as client:
            async def one(c: dict[str, Any]) -> Optional[dict[str, Any]]:
                async with sem:
                    lc = c.get("location_code")
                    coord = f"{c['latitude']},{c['longitude']},13z"
                    try:
                        # demand (both keyword forms, one task)
                        vp = await la._dfs_post(
                            client, "/keywords_data/google_ads/search_volume/task_post",
                            [{"location_code": int(lc), "language_name": "English",
                              "keywords": [keyword, keyword + " near me"]}])
                        t0 = la._task0(vp); la._check_money_limit(t0)
                        vres = await la._poll_task(
                            client, "/keywords_data/google_ads/search_volume/task_get",
                            t0.get("id"), interval_s=10, attempts=40)
                        demand = la.demand_from_items(vres or [], [keyword]).get(keyword, {})
                        # supply (Maps SERP 13z)
                        d = await la._dfs_post(
                            client, "/serp/google/maps/live/advanced",
                            [{"keyword": keyword, "location_coordinate": coord,
                              "language_code": "en", "device": "desktop",
                              "os": "windows", "depth": 100}])
                        s0 = la._task0(d); la._check_money_limit(s0)
                        items = ([] if s0.get("status_code") == la._CODE_NO_RESULTS
                                 else ((s0.get("result") or [{}])[0] or {}).get("items") or [])
                        field = {category: la.field_stats(items, category)}
                    except RuntimeError:
                        raise
                    except Exception as exc:
                        logger.warning("leadoff_city_finder.city_failed",
                                       extra={"city": c.get("name"), "error": str(exc)})
                        return None
                rows = la.tryout_rows({category: demand}, field,
                                      {category: lead_value}, breakpoints,
                                      DEFAULT_CAPTURE)
                if not rows:
                    return None
                r = rows[0]
                return {**r, "city_id": c["city_id"], "city_name": c["name"],
                        "state_code": c["state_code"], "population": c["population"]}

            gathered = await asyncio.gather(*(one(c) for c in cities))
        results = [r for r in gathered if r]
        results.sort(key=lambda r: r.get("exp_val") or 0, reverse=True)

        supabase.table("leadoff_city_finder_runs").update({
            "status": "complete", "completed_at": "now()",
            "results": results,
            "result_meta": {"cities_scanned": len(cities),
                            "cities_scored": len(results),
                            "lead_value_used": lead_value,
                            "lead_value_source": (
                                "table" if cpl_map.get(category) else "default/override")},
        }).eq("id", run_id).execute()
        supabase.table("async_jobs").update({
            "status": "complete", "completed_at": "now()",
            "result": {"cities_scored": len(results)},
        }).eq("id", job["id"]).execute()
        logger.info("leadoff_city_finder.complete",
                    extra={"run_id": run_id, "scored": len(results)})
    except Exception as exc:
        logger.error("leadoff_city_finder.failed",
                     extra={"job_id": job["id"], "error": str(exc)})
        _fail(str(exc))
