"""LeadOff grade-all — the board/cache-aware bulk "rank every city for a service".

The cross-city sort the precomputed board can't do. The board is ≥30k pop and
scanned-category only, so it can only rank cities for a service that was
precomputed. grade-all reaches the sub-30k + off-catalog cities the board never
scanned by grading the exact city×service cells on demand, cheapest-path-first
per city (the single-cell grader's logic, transposed to N cities):

  1. board-first (FREE)  — an exact city×category already on leadoff_board.
  2. cache (FREE)        — a recent live grade for this city×service.
  3. live (PAID, ~$0.06) — one Google Ads keyword task (both forms) + one Maps
     SERP @ 13z → the SAME tryout economics/grade math, scoped to one service.

Each live grade is persisted to leadoff_grades (the single-cell grader's cache),
so the sweep is naturally idempotent/resumable on a reaper requeue (a re-run
finds those cells cached = free) and future lookups of those cells are free too.

Spend is bounded three ways — the caller's per-run `max_spend` ceiling (a hard
stop on live grading, enforced by pre-selecting only as many cities as the
ceiling covers), a dedicated per-user daily grade_all budget (separate from the
tight $5 single-grade guard), and a candidate-city cap. Nothing spends without
staff auth + an explicit confirm + a max_spend ceiling.

The pure helpers (split_candidates / plan_live_budget / normalize_row /
rank_rows / estimate_cost) are unit-tested in tests/test_leadoff_grade_all.py;
the impure reads + job reuse leadoff_actions' DataForSEO plumbing wholesale.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from db.supabase_client import get_supabase
from services import leadoff_actions as la
from services import leadoff_grade as lg
from services.leadoff import _norm as norm

logger = logging.getLogger(__name__)

COST_GRADE = lg.COST_GRADE            # ~$0.06 per live single-cell grade
FRESH_DAYS = la.FRESH_DAYS            # 90 — a city×service grade is stable for weeks


# ── Pure helpers ──────────────────────────────────────────────────────────────

def estimate_cost(needs_live: int) -> float:
    """Live cost = ungraded cells × the single-cell grade cost. Board + cache
    hits are free, so only the live remainder is billed."""
    return round(max(0, int(needs_live)) * COST_GRADE, 2)


def plan_live_budget(needs_live: int, max_spend: float, cost_each: float = COST_GRADE) -> int:
    """How many cities the caller's per-run ceiling lets us grade live —
    min(cells that need grading, cells the ceiling covers). A 0/negative ceiling
    grades nothing live (board/cache only). Pure."""
    if cost_each <= 0:
        return int(needs_live)
    affordable = int(max(0.0, float(max_spend)) // cost_each)
    return max(0, min(int(needs_live), affordable))


def split_candidates(candidates: list[dict[str, Any]], board_free_ids: set[int],
                     cached_ids: set[int]) -> dict[str, list[dict[str, Any]]]:
    """Partition candidate cities into {on_board, cached, needs_live} by the
    cheapest source that answers each — board wins over cache, cache over live.
    Order within each bucket is preserved (candidates arrive population-desc, so
    needs_live grades the biggest markets first). Pure."""
    on_board, cached, needs_live = [], [], []
    for c in candidates:
        cid = c.get("city_id")
        if cid in board_free_ids:
            on_board.append(c)
        elif cid in cached_ids:
            cached.append(c)
        else:
            needs_live.append(c)
    return {"on_board": on_board, "cached": cached, "needs_live": needs_live}


def normalize_row(source: str, raw: dict[str, Any], *, category_name: str,
                  population: Optional[int]) -> dict[str, Any]:
    """One thin, comparable ranked row from any of the three sources (board row /
    cached grade / live grade). Demand differs by source — the board carries the
    regressed `xdem`, live/cache the raw observed `vol` — so both are surfaced
    under `demand` + `demand_basis` for honesty. Pure."""
    observed = source in ("cache", "live")
    return {
        "city_id": raw.get("city_id"),
        "city_name": raw.get("city_name"),
        "state_code": raw.get("state_code"),
        "population": population if population is not None else raw.get("population"),
        "category": raw.get("category") or category_name,
        "grade": raw.get("grade"),
        "exp_val": raw.get("exp_val"),
        "value_mo": raw.get("value_mo"),
        "rankab": raw.get("rankab"),
        "roi": raw.get("roi"),
        "rev_win": raw.get("rev_win"),
        "rating": raw.get("rating"),
        "exact_open": raw.get("exact_open"),
        "namekw": raw.get("namekw"),
        "supply": raw.get("supply"),
        "beatability": raw.get("beatability"),
        "beatability_band": raw.get("beatability_band"),
        "demand": raw.get("vol") if observed else raw.get("xdem"),
        "demand_basis": "observed" if observed else "regressed",
        "thin_demand": raw.get("thin_demand"),
        "source": source,
    }


def rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort the merged sweep by expected value (the board's own 'expected' sort,
    comparable across all three sources), then monthly value, then city. Pure."""
    def _n(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return sorted(rows, key=lambda r: (-_n(r.get("exp_val")), -_n(r.get("value_mo")),
                                       (r.get("city_name") or "")))


# ── Impure reads ──────────────────────────────────────────────────────────────

def candidate_cities(*, state: Optional[str], min_pop: int, max_pop: Optional[int],
                     limit: int) -> list[dict[str, Any]]:
    """Population-ranked gradeable US cities (market_scanner.cities) — a Google
    Ads location_code is required (demand pull needs it). Capped at `limit`."""
    q = (la._ms("cities")
         .select("city_id, name, state_code, population, latitude, longitude, location_code")
         .not_.is_("location_code", "null")
         .gte("population", int(min_pop)))
    if max_pop is not None:
        q = q.lte("population", int(max_pop))
    if state:
        q = q.eq("state_code", state.upper())
    rows = (q.order("population", desc=True).limit(int(limit)).execute().data or [])
    # normalize to the shape the rest of this module expects (name → city_name)
    for r in rows:
        r["city_name"] = r.get("name")
    return rows


def board_free_rows(category_id: Optional[str],
                    city_ids: set[int]) -> dict[int, dict[str, Any]]:
    """Full leadoff_board rows for this category, keyed by city_id, restricted to
    the candidate set. Empty for an off-catalog service (no category_id)."""
    if not category_id or not city_ids:
        return {}
    from services.leadoff_db import get_leadoff_client
    rows = (get_leadoff_client().table("leadoff_board").select("*")
            .eq("category_id", str(category_id)).execute().data or [])
    return {r["city_id"]: r for r in rows if r.get("city_id") in city_ids}


def cached_grade_rows(keyword: str, city_ids: set[int],
                      now: Optional[datetime] = None) -> dict[int, dict[str, Any]]:
    """Freshest complete live grade per candidate city for this LITERAL keyword,
    keyed by city_id. Matches on the cache_key's normalized-keyword suffix so a
    run picks up cells graded by an earlier grade-all or single grade of the same
    keyword."""
    if not city_ids:
        return {}
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=FRESH_DAYS)).isoformat()
    rows = (get_supabase().table("leadoff_grades")
            .select("city_id, city_name, state_code, grade, pulled_at")
            .eq("status", "complete").gte("pulled_at", cutoff)
            .ilike("cache_key", f"%|{norm(keyword)}")
            .order("pulled_at", desc=True).execute().data or [])
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        cid = r.get("city_id")
        if cid in city_ids and cid not in out:   # newest-first → first wins
            out[cid] = r
    return out


def estimate(*, keyword: str, category_id: Optional[str], on_catalog: bool,
             state: Optional[str], min_pop: int, max_pop: Optional[int],
             limit: int) -> dict[str, Any]:
    """Free preview: how many candidate cities, the board/cache-free split, and
    the live cost of the remainder. No spend, no enqueue. Cache hits are keyed on
    the literal keyword; board hits on the mapped category id."""
    cities = candidate_cities(state=state, min_pop=min_pop, max_pop=max_pop, limit=limit)
    ids = {c["city_id"] for c in cities}
    board_ids = set(board_free_rows(category_id if on_catalog else None, ids).keys())
    cache_ids = set(cached_grade_rows(keyword, ids - board_ids).keys())
    split = split_candidates(cities, board_ids, cache_ids)
    needs_live = len(split["needs_live"])
    return {
        "cities": len(cities), "on_board": len(split["on_board"]),
        "cached": len(split["cached"]), "needs_live": needs_live,
        "est_cost": estimate_cost(needs_live),
    }


# ── Enqueue + the async sweep ─────────────────────────────────────────────────

def enqueue_grade_all(user_id: str, *, service_query: str, keyword: str,
                      lead_category: Optional[str], category_id: Optional[str],
                      on_catalog: bool, state: Optional[str], min_pop: int,
                      max_pop: Optional[int], limit: int, capture: float,
                      lead_tier: str, cpl: float, cpl_default: bool,
                      max_spend: float, est_cost: float) -> dict[str, Any]:
    """Create the run row + async job. The run's category_name is the LITERAL
    keyword graded (display + cache); the catalog category (for CPL/holders)
    rides in the payload as lead_category."""
    supabase = get_supabase()
    run = supabase.table("leadoff_grade_all_runs").insert({
        "requested_by": user_id, "service_query": service_query,
        "category_name": keyword, "category_id": category_id,
        "on_catalog": on_catalog, "state": (state.upper() if state else None),
        "min_pop": int(min_pop), "max_pop": (int(max_pop) if max_pop else None),
        "capture": capture, "lead_tier": lead_tier, "cpl": round(float(cpl), 2),
        "cpl_default": cpl_default, "max_spend": round(float(max_spend), 2),
        "est_cost": est_cost, "status": "pending",
    }).execute().data[0]
    job = supabase.table("async_jobs").insert({
        "job_type": "leadoff_grade_all", "entity_id": run["id"],
        "payload": {"run_id": run["id"], "user_id": user_id,
                    "service_query": service_query, "keyword": keyword,
                    "lead_category": lead_category, "category_id": category_id,
                    "on_catalog": on_catalog, "state": state, "min_pop": int(min_pop),
                    "max_pop": (int(max_pop) if max_pop else None), "limit": int(limit),
                    "capture": capture, "lead_tier": lead_tier, "cpl": cpl,
                    "cpl_default": cpl_default, "max_spend": float(max_spend)},
    }).execute().data[0]
    return {"run_id": run["id"], "job_id": job["id"], "est_cost": est_cost}


async def _grade_one_live(client: httpx.AsyncClient, city: dict[str, Any], *,
                          keyword: str, lead_category: Optional[str],
                          category_id: Optional[str],
                          on_catalog: bool, service_query: str, cpl: float,
                          cpl_default: bool, breakpoints: list[float],
                          capture: float, lead_tier: str,
                          user_id: Optional[str],
                          cpc_median: Optional[float] = None,
                          cpc_bounds: Optional[dict[str, float]] = None,
                          city_income: Optional[float] = None,
                          income_params: Optional[dict[str, Any]] = None
                          ) -> Optional[dict[str, Any]]:
    """Live-grade one city on the LITERAL keyword (mirrors
    leadoff_grade.run_grade_job's body), enrich, persist to leadoff_grades
    (cache/resume), and return the normalized row. Exact-category holders are
    counted against the mapped catalog category (lead_category) when there is
    one. Returns None on a per-city failure (dropped, like city-finder)."""
    now = datetime.now(timezone.utc)
    try:
        vol: Optional[float] = None
        cpc: Optional[float] = None
        lc = la._location_code(city)
        if lc:
            posted = await la._dfs_post(
                client, "/keywords_data/google_ads/search_volume/task_post",
                [{"location_code": lc, "language_name": "English",
                  "keywords": [keyword, keyword + " near me"]}])
            task = la._task0(posted)
            la._check_money_limit(task)
            result = await la._poll_task(
                client, "/keywords_data/google_ads/search_volume/task_get",
                task.get("id"), interval_s=10, attempts=40)
            dem = la.demand_from_items(result or [], [keyword]).get(keyword, {})
            vol, cpc = dem.get("vol"), dem.get("cpc")

        from services.leadoff_brand import top5_from_items
        coord = f"{city['latitude']},{city['longitude']},13z"
        d = await la._dfs_post(
            client, "/serp/google/maps/live/advanced",
            [{"keyword": keyword, "location_coordinate": coord,
              "language_code": "en", "device": "desktop", "os": "windows", "depth": 100}])
        t0 = la._task0(d)
        la._check_money_limit(t0)
        items = ([] if t0.get("status_code") == la._CODE_NO_RESULTS
                 else ((t0.get("result") or [{}])[0] or {}).get("items") or [])
        field = la.field_stats(items, keyword, holder_category=lead_category)
        competitors = top5_from_items(items)
    except RuntimeError:
        raise                      # money-limit → abort the whole sweep
    except Exception as exc:
        logger.warning("leadoff_grade_all.city_failed",
                       extra={"city": city.get("city_name"), "error": str(exc)})
        return None

    # per-market local modifier (valuation plan §3): the national CPC median for
    # this sweep's category is loaded once (cpc_median); income is this city's
    # median household income (batch-loaded once for the sweep). Blended when
    # income_params is present, CPC-only otherwise; ×1.0 when a signal is
    # absent/thin.
    cpl_mult = 1.0
    cpl_detail: Optional[dict[str, Any]] = None
    if income_params is not None and cpc_bounds is not None:
        from services import leadoff_income_modifier as lim
        _key = str(lead_category or keyword).lower()
        cpl_mult, cpl_detail = lim.local_modifier(
            cpc, _key, city_income, {_key: cpc_median}, income_params)
    elif cpc_bounds is not None:
        from services import leadoff_cpc
        cpl_mult = leadoff_cpc.cpc_modifier(cpc, cpc_median, **cpc_bounds)
    row = lg.build_grade_row(
        keyword=keyword, category_id=category_id, lead_category=lead_category,
        vol=vol, cpc=cpc, field=field, cpl=cpl, cpl_default=cpl_default,
        breakpoints=breakpoints, capture=capture, competitors=competitors,
        cpl_multiplier=cpl_mult, cpl_modifier_detail=cpl_detail)
    try:
        from services.leadoff_beatability import attach_beatability
        from services.leadoff_roi import attach_roi
        row = [attach_roi(r) for r in attach_beatability([row])][0]
    except Exception:
        logger.warning("leadoff_grade_all.enrich_failed", exc_info=True)

    # Persist to the single-cell cache — makes this cell free next time and lets
    # a reaper requeue of this sweep resume from cache instead of re-paying.
    try:
        get_supabase().table("leadoff_grades").insert({
            "requested_by": user_id, "city_id": city.get("city_id"),
            "city_name": city.get("city_name"), "state_code": city.get("state_code"),
            "category_id": category_id, "category_name": keyword,
            "service_query": service_query,
            "cache_key": lg.cache_key(city.get("city_id"), keyword),
            "capture": capture, "lead_tier": lead_tier, "on_catalog": on_catalog,
            "cpl_default": cpl_default, "source": "live", "status": "complete",
            "grade": row, "pulled_at": now.isoformat(), "completed_at": "now()",
        }).execute()
    except Exception as exc:
        logger.warning("leadoff_grade_all.cache_write_failed",
                       extra={"city": city.get("city_name"), "error": str(exc)})

    return normalize_row("live", {**row, "city_id": city.get("city_id"),
                                  "city_name": city.get("city_name"),
                                  "state_code": city.get("state_code")},
                         category_name=keyword, population=city.get("population"))


async def run_grade_all_job(job: dict) -> None:
    """Grade every candidate city for one service: board/cache free, live for the
    remainder up to the caller's max_spend ceiling. Ranked results on the run."""
    supabase = get_supabase()
    payload = job.get("payload") or {}
    run_id = payload["run_id"]
    # `keyword` is the literal term graded; `lead_category` the catalog category
    # the CPL + exact-holder count come from (may be None). (Back-compat: a job
    # enqueued before this change carries only `category_name`.)
    keyword = payload.get("keyword") or payload.get("category_name") or ""
    lead_category = payload.get("lead_category") or (
        payload.get("category_name") if payload.get("category_id") else None)
    category_id = payload.get("category_id")
    on_catalog = bool(payload.get("on_catalog"))
    capture = float(payload.get("capture") or 0.10)
    lead_tier = payload.get("lead_tier") or "mid"
    cpl = float(payload.get("cpl") or 0.0)
    cpl_default = bool(payload.get("cpl_default"))
    max_spend = float(payload.get("max_spend") or 0.0)
    user_id = payload.get("user_id")
    from config import settings

    def _fail(err: str) -> None:
        supabase.table("leadoff_grade_all_runs").update(
            {"status": "failed", "error": err[:500], "completed_at": "now()"}
        ).eq("id", run_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": err[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()

    try:
        supabase.table("leadoff_grade_all_runs").update({"status": "running"}) \
            .eq("id", run_id).execute()
        cities = candidate_cities(state=payload.get("state"),
                                  min_pop=int(payload.get("min_pop") or 10000),
                                  max_pop=payload.get("max_pop"),
                                  limit=int(payload.get("limit")
                                            or settings.leadoff_grade_all_max_cities))
        if not cities:
            _fail("no_candidate_cities")
            return
        ids = {c["city_id"] for c in cities}
        board_rows = board_free_rows(category_id if on_catalog else None, ids)
        cache_rows = cached_grade_rows(keyword, ids - set(board_rows))
        split = split_candidates(cities, set(board_rows), set(cache_rows))
        needs_live = split["needs_live"]

        # pre-select only as many live cities as the per-run ceiling covers
        # (biggest markets first — candidates are population-desc)
        allowed = plan_live_budget(len(needs_live), max_spend, COST_GRADE)
        to_grade = needs_live[:allowed]
        budget_skipped = needs_live[allowed:]

        # free rows first (board + cache), normalized
        results: list[dict[str, Any]] = []
        for c in split["on_board"]:
            results.append(normalize_row("board", board_rows[c["city_id"]],
                                         category_name=keyword,
                                         population=c.get("population")))
        for c in split["cached"]:
            g = cache_rows[c["city_id"]]
            inner = {**(g.get("grade") or {}), "city_id": c["city_id"],
                     "city_name": c.get("city_name"), "state_code": c.get("state_code")}
            results.append(normalize_row("cache", inner, category_name=keyword,
                                         population=c.get("population")))

        # live remainder (bounded concurrency)
        graded_live = 0
        if to_grade:
            breakpoints = la._breakpoints()
            sem = asyncio.Semaphore(int(settings.leadoff_grade_all_concurrency))
            # per-market local modifier (valuation plan §3): one national CPC
            # median for this sweep's category + the bounds, loaded once; income
            # is per-city, batch-loaded once for the live remainder.
            from services import leadoff_cpc
            from services import leadoff_income_modifier as lim
            _cpc_bounds = leadoff_cpc.bounds()
            _cpc_median = leadoff_cpc.baseline_map().get(
                str(lead_category or keyword).lower())
            _income_params = lim.params()
            _income_by_city = (lim.income_map([c["city_id"] for c in to_grade])
                               if _income_params["enabled"] else {})

            async def one(c: dict[str, Any]) -> Optional[dict[str, Any]]:
                async with sem:
                    return await _grade_one_live(
                        client, c, keyword=keyword, lead_category=lead_category,
                        category_id=category_id, on_catalog=on_catalog,
                        service_query=payload.get("service_query") or "",
                        cpl=cpl, cpl_default=cpl_default, breakpoints=breakpoints,
                        capture=capture, lead_tier=lead_tier, user_id=user_id,
                        cpc_median=_cpc_median, cpc_bounds=_cpc_bounds,
                        city_income=_income_by_city.get(c["city_id"]),
                        income_params=_income_params)

            async with httpx.AsyncClient() as client:
                gathered = await asyncio.gather(*(one(c) for c in to_grade))
            live_rows = [r for r in gathered if r]
            graded_live = len(live_rows)
            results.extend(live_rows)

        ranked = rank_rows(results)
        cost_spent = round(len(to_grade) * COST_GRADE, 2)
        budget_reached = bool(budget_skipped)
        meta = {
            "cities": len(cities), "on_board": len(split["on_board"]),
            "cached": len(split["cached"]), "needs_live": len(needs_live),
            "graded_live": graded_live, "budget_skipped": len(budget_skipped),
            "cost_spent": cost_spent, "budget_reached": budget_reached,
            "lead_value_used": round(float(cpl), 2), "cpl_default": cpl_default,
        }
        supabase.table("leadoff_grade_all_runs").update({
            "status": "partial" if budget_reached else "complete",
            "completed_at": "now()", "results": ranked, "result_meta": meta,
        }).eq("id", run_id).execute()
        supabase.table("async_jobs").update({
            "status": "complete", "completed_at": "now()",
            "result": {"ranked": len(ranked), "graded_live": graded_live,
                       "cost_spent": cost_spent},
        }).eq("id", job["id"]).execute()
        logger.info("leadoff_grade_all.complete",
                    extra={"run_id": run_id, "ranked": len(ranked),
                           "graded_live": graded_live, "cost_spent": cost_spent})
    except Exception as exc:
        logger.error("leadoff_grade_all.failed",
                     extra={"job_id": job["id"], "error": str(exc)})
        _fail(str(exc))
