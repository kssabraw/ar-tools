"""LeadOff on-demand market grader — "type a city + a service → get a grade".

The single-cell complement to the whole-board precompute and the tryout (which
grades ALL ~100 categories for a city, ~$1, ~3 min). Resolves a typed service to
a board category, then serves the grade by the cheapest path that answers it:

  1. **board-first (FREE)** — if the exact city×category is already on the
     precomputed board, return its enriched brief grade (get_market_brief); no
     API spend.
  2. **cache (FREE)** — a recent live grade for this city×service (< FRESH_DAYS).
  3. **live (PAID, ~a few cents)** — one Google Ads keyword task (both forms) +
     one Maps SERP @ 13z → the SAME rankability/exp_val/grade math the tryout
     uses (`leadoff_actions.tryout_rows`), scoped to the one requested service.
     Persisted to `leadoff_grades` so a repeat lookup is free.

Unlike the board/tryout, the live path does NOT apply the vol>=20 demand gate —
the user asked for THIS cell, so it is graded regardless and the demand is
surfaced (`thin_demand` when < MIN_VOL). The gate only ever bounded the cost of
PRECOMPUTING thousands of cells.

Off-catalog services (not one of the ~100 GBP categories) still grade live: the
keyword + SERP work for any term; only the lead value (CPL) needs a fallback —
`leadoff_finder_default_lead_value`, flagged `cpl_default=True`.

The pure helpers (resolve_service / cache_key / resolve_cpl / build_grade_row /
thin_demand) are unit-tested in tests/test_leadoff_grade.py; the impure job +
reads reuse leadoff_actions' DataForSEO plumbing wholesale.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from db.supabase_client import get_supabase
from services import leadoff_actions as la
from services.leadoff import _norm as norm

logger = logging.getLogger(__name__)

# One keyword task (~$0.05, per-task billing) + one Maps SERP @ 13z (~$0.004).
COST_GRADE = 0.06
FRESH_DAYS = la.FRESH_DAYS  # 90 — a city×service grade is stable for weeks


# ── Pure helpers ──────────────────────────────────────────────────────────────

def resolve_service(service: str, board_categories: list[str]) -> dict[str, Any]:
    """Resolve a typed service into the grade KEYWORD (always the literal input —
    what the live demand + Maps SERP pull actually uses) plus the nearest catalog
    CATEGORY, used ONLY for the lead value (CPL), the exact-category holder count,
    and the board/scout id — never as the pulled keyword. So "roofer" grades
    "roofer" (its own volume + SERP) while still borrowing "Roofing contractor"'s
    CPL. Returns {keyword, category_name (catalog match or None), on_catalog}."""
    from services.leadoff_finder import resolve_category
    cleaned = " ".join((service or "").split()).strip()
    match = resolve_category(cleaned, board_categories) if cleaned else None
    return {"keyword": cleaned, "category_name": match, "on_catalog": match is not None}


def cache_key(city_id: int, keyword: str) -> str:
    """Freshness key for the grade cache — city + the normalized LITERAL keyword
    that was graded. Keyed on the keyword (not the catalog category) so "roofer"
    and "roofing contractor" — which pull different SERPs — cache distinctly."""
    return f"{int(city_id)}|{norm(keyword)}"


def resolve_cpl(category_name: str, lead_values: dict[str, float],
                default: float) -> tuple[float, bool]:
    """(cpl, is_default). Exact case-insensitive match against the lead-values
    catalog; off-catalog services fall back to the flagged default."""
    by_lower = {str(k).lower(): v for k, v in (lead_values or {}).items()}
    hit = by_lower.get((category_name or "").lower())
    if hit is not None:
        return float(hit), False
    return float(default), True


def thin_demand(vol: Optional[float]) -> bool:
    """True when measured demand is below the board's gate — surfaced, never
    used to withhold the grade (the on-demand resolution of the gate debate)."""
    return vol is not None and float(vol) < la.MIN_VOL


def build_grade_row(*, keyword: str, category_id: Optional[str],
                    vol: Optional[float], cpc: Optional[float],
                    field: dict[str, Any], cpl: float, cpl_default: bool,
                    breakpoints: list[float], capture: float,
                    competitors: Optional[list[dict[str, Any]]] = None,
                    lead_category: Optional[str] = None,
                    cpl_multiplier: float = 1.0,
                    cpl_modifier_detail: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Compose the single grade row from measured demand + a SERP field read,
    reusing the tryout's economics/grade math (one keyword in, one row out).
    `keyword` is the LITERAL term graded (its own volume + SERP → row.category
    for display); `lead_category` is the catalog category the CPL + exact-holder
    count came from (recorded for transparency, may be None). `cpl_multiplier` is
    the per-market local modifier (valuation plan §3, CPC + income; 1.0 = flat CPL,
    the default, so ``row['cpl']`` == the input CPL). `cpl_modifier_detail` (which
    signals fed it, optional) is stamped onto the row for transparency. Pure — no
    I/O."""
    rows = la.tryout_rows(
        demand={keyword: {"vol": vol, "cpc": cpc}},
        field={keyword: field},
        cpl={keyword: cpl},
        breakpoints=breakpoints,
        capture=capture,
        cpl_multipliers={keyword: cpl_multiplier},
        cpl_modifier_details=({keyword: cpl_modifier_detail}
                              if cpl_modifier_detail is not None else None),
    )
    row = rows[0] if rows else {"category": keyword, "grade": "F", "exp_val": 0}
    row["category_id"] = category_id
    row["lead_category"] = lead_category
    row["thin_demand"] = thin_demand(vol)
    # tryout_rows sets cpl_base / cpl_modifier / cpl (effective); don't clobber.
    row["cpl_default"] = cpl_default
    if competitors is not None:
        row["competitors"] = competitors
    return row


# ── Board-first + cache reads (FREE) ──────────────────────────────────────────

def board_hit(city_id: int, category_id: Optional[str]) -> Optional[dict[str, Any]]:
    """The enriched brief grade when the exact market is already on the
    precomputed board — free, no API spend. None when off-board/off-catalog."""
    if not category_id:
        return None
    from services import leadoff as leadoff_service
    try:
        return leadoff_service.get_market_brief(int(city_id), str(category_id))
    except Exception:
        logger.warning("leadoff_grade.board_hit_failed",
                       extra={"city_id": city_id, "category_id": category_id},
                       exc_info=True)
        return None


def fresh_cached(city_id: int, category_name: str,
                 now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """The newest complete live grade for this city×service within FRESH_DAYS."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=FRESH_DAYS)).isoformat()
    rows = (get_supabase().table("leadoff_grades").select("*")
            .eq("cache_key", cache_key(city_id, category_name))
            .eq("status", "complete").gte("pulled_at", cutoff)
            .order("pulled_at", desc=True).limit(1).execute().data or [])
    return rows[0] if rows else None


# ── Live single-cell grade (PAID) ─────────────────────────────────────────────

def enqueue_grade(user_id: str, city_row: dict[str, Any], keyword: str,
                  lead_category: Optional[str], category_id: Optional[str],
                  on_catalog: bool, service_query: str, capture: float,
                  lead_tier: str) -> dict[str, Any]:
    """Create the leadoff_grades row (status running) + the async job that fills
    it. The row's category_name is the LITERAL keyword (what's graded + cached);
    the catalog category (for CPL/scout) rides in the job payload as
    lead_category. Poll GET /leadoff/grade/{grade_id}."""
    supabase = get_supabase()
    grade = supabase.table("leadoff_grades").insert({
        "requested_by": user_id,
        "city_id": city_row.get("city_id"),
        "city_name": city_row.get("name"),
        "state_code": city_row.get("state_code"),
        "category_id": category_id,
        "category_name": keyword,
        "service_query": service_query,
        "cache_key": cache_key(city_row.get("city_id"), keyword),
        "capture": capture, "lead_tier": lead_tier,
        "on_catalog": on_catalog, "source": "live", "status": "running",
    }).execute().data[0]
    job = supabase.table("async_jobs").insert({
        "job_type": "leadoff_grade",
        "entity_id": grade["id"],
        "payload": {"grade_id": grade["id"], "city_id": city_row.get("city_id"),
                    "keyword": keyword, "lead_category": lead_category,
                    "category_id": category_id,
                    "capture": capture, "lead_tier": lead_tier},
    }).execute().data[0]
    return {"grade": grade, "grade_id": grade["id"], "job_id": job["id"]}


async def run_grade_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    grade_id = payload.get("grade_id")
    # `keyword` is the literal term graded; `lead_category` the catalog category
    # the CPL + exact-holder count come from. (Back-compat: an in-flight job
    # enqueued before this change carries only `category_name` — treat it as both.)
    keyword = payload.get("keyword") or payload.get("category_name") or ""
    lead_category = payload.get("lead_category") or (
        payload.get("category_name") if payload.get("category_id") else None)
    category_id = payload.get("category_id")
    capture = float(payload.get("capture") or 0.10)
    lead_tier = payload.get("lead_tier") or "mid"

    def _fail(err: str) -> None:
        supabase.table("leadoff_grades").update(
            {"status": "failed", "error": err[:500], "completed_at": "now()"}
        ).eq("id", grade_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": err[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

    try:
        city = (la._ms("cities").select("*")
                .eq("city_id", payload["city_id"]).limit(1).execute().data or [None])[0]
        if not city:
            _fail("city_not_found")
            return
        now = datetime.now(timezone.utc)

        async with httpx.AsyncClient() as client:
            # 1) demand + CPC — one keyword task, both forms (lesson #4)
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
                    task.get("id"), interval_s=8, attempts=45)
                dem = la.demand_from_items(result or [], [keyword])
                vol = dem.get(keyword, {}).get("vol")
                cpc = dem.get(keyword, {}).get("cpc")

            # 2) one Maps SERP live @ 13z (lesson #1); 40102 = a VALID zero.
            # The SERP is pulled on the LITERAL keyword; exact-category holders
            # are counted against the catalog category when we matched one.
            from services.leadoff_brand import top5_from_items
            coord = f"{city['latitude']},{city['longitude']},13z"
            d = await la._dfs_post(
                client, "/serp/google/maps/live/advanced",
                [{"keyword": keyword, "location_coordinate": coord,
                  "language_code": "en", "device": "desktop", "os": "windows",
                  "depth": 100}])
            t0 = la._task0(d)
            la._check_money_limit(t0)
            if t0.get("status_code") == la._CODE_NO_RESULTS:
                items: list[dict[str, Any]] = []
            else:
                items = ((t0.get("result") or [{}])[0] or {}).get("items") or []
            field = la.field_stats(items, keyword, holder_category=lead_category)
            competitors = top5_from_items(items)

        # 3) economics + grade vs the national reference; CPL from the nearest
        # catalog category (flagged default when off-catalog).
        cpl, cpl_default = resolve_cpl(
            lead_category or keyword, la._lead_values(lead_tier),
            __import__("config").settings.leadoff_finder_default_lead_value)
        # per-market local modifier (valuation plan §3): CPC (keyed on the catalog
        # category the CPL came from — the national baseline is per category) +
        # income (this city's median household income vs the national median),
        # blended. ×1.0 until the CPC baseline is populated / on any thin CPC; the
        # income half is byte-identical-off when disabled or the city has no income.
        from services import (
            leadoff_cpc,
            leadoff_income_modifier as lim,
            leadoff_monetization,
        )
        _p = lim.params()
        _income = lim.city_income(city.get("city_id")) if _p["enabled"] else None
        cpl_mult, cpl_detail = lim.local_modifier(
            cpc, lead_category or keyword, _income, leadoff_cpc.baseline_map(), _p)
        row = build_grade_row(
            keyword=keyword, category_id=category_id, lead_category=lead_category,
            vol=vol, cpc=cpc, field=field, cpl=cpl, cpl_default=cpl_default,
            breakpoints=la._breakpoints(), capture=capture,
            competitors=competitors, cpl_multiplier=cpl_mult,
            cpl_modifier_detail=cpl_detail)
        try:
            from services.leadoff_beatability import attach_beatability
            from services.leadoff_roi import attach_roi
            row = [attach_roi(r) for r in attach_beatability([row])][0]
        except Exception:
            logger.warning("leadoff_grade.enrich_failed", exc_info=True)
        leadoff_monetization.attach(row)  # PPL / rank-and-rent / shared print

        supabase.table("leadoff_grades").update({
            "status": "complete", "grade": row, "cpl_default": cpl_default,
            "pulled_at": now.isoformat(), "completed_at": "now()",
        }).eq("id", grade_id).execute()
        supabase.table("async_jobs").update({
            "status": "complete", "completed_at": "now()",
            "result": {"grade": row.get("grade"), "exp_val": row.get("exp_val")},
        }).eq("id", job_id).execute()
        logger.info("leadoff_grade.complete", extra={
            "grade_id": grade_id, "keyword": keyword, "lead_category": lead_category,
            "grade": row.get("grade"), "thin_demand": row.get("thin_demand")})
    except Exception as exc:
        logger.error("leadoff_grade.failed",
                     extra={"job_id": job_id, "error": str(exc)})
        _fail(str(exc))


# ── Scout a graded (off-board) market ─────────────────────────────────────────
# A live grade already pulled the market's top-5 competitors; scout deepens them
# (RD / review velocity / demand trend / brand footprint) WITHOUT needing a board
# row. Reuses the leadoff_scout job (grade_id in the payload); the enrichment is
# stored back on the grade row's `scout` column for the grade card to render.

def scoutable(grade_row: dict[str, Any]) -> Optional[str]:
    """Error code if this grade row can't be scouted, else None (pure). Scout
    keys on a real category_id (on-catalog) and needs the graded competitor set."""
    if grade_row.get("status") != "complete":
        return "grade_not_ready"
    if not grade_row.get("on_catalog") or not grade_row.get("category_id"):
        return "scout_requires_catalog"
    if not (((grade_row.get("grade") or {}).get("competitors")) or []):
        return "no_competitors"
    return None


def grade_market_comps(grade_row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(market, comps) for scout_market_state, built from a grade row's stored
    top-5 — the off-board substitute for the board row + serp_top5 (pure)."""
    g = grade_row.get("grade") or {}
    # Scout keys on the catalog CATEGORY (that's how the scanner's Pass-2 caches
    # are keyed) — the grade's lead_category — not the literal keyword now stored
    # in category_name. Older rows have no lead_category, so fall back.
    scout_category = g.get("lead_category") or grade_row.get("category_name")
    market = {"city_id": grade_row.get("city_id"),
              "category_id": grade_row.get("category_id"),
              "category": scout_category,
              "city_name": grade_row.get("city_name"),
              "state_code": grade_row.get("state_code")}
    comps = [{"rank_position": i + 1, **c}
             for i, c in enumerate(g.get("competitors") or [])]
    return market, comps


def grade_scout_inputs(grade_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a grade row and return (market, comps) for the scout job. Raises when
    the row is gone or unscoutable (surfaces as the job's failure reason)."""
    row = (get_supabase().table("leadoff_grades").select("*")
           .eq("id", grade_id).limit(1).execute().data or [None])[0]
    if not row:
        raise RuntimeError("grade_not_found")
    err = scoutable(row)
    if err:
        raise RuntimeError(err)
    return grade_market_comps(row)


def store_scout_result(grade_id: str,
                       summary: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Read the now-fresh Pass-2 caches for the graded market and store the
    enrichment on the grade row's `scout` column (the off-board analogue of the
    brief's enrichment re-read). Best-effort — returns the stored block or None."""
    from services import leadoff as leadoff_service
    row = (get_supabase().table("leadoff_grades").select("*")
           .eq("id", grade_id).limit(1).execute().data or [None])[0]
    if not row:
        return None
    market, comps = grade_market_comps(row)
    scout = leadoff_service.scout_enrichment(
        int(row["city_id"]), market.get("category") or "", comps)
    payload = {"enrichment": scout["enrichment"], "competitors": scout["competitors"],
               "summary": summary or {},
               "scouted_at": datetime.now(timezone.utc).isoformat()}
    get_supabase().table("leadoff_grades").update({"scout": payload}).eq("id", grade_id).execute()
    return payload
