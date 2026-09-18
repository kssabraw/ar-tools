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
    """Map a typed service to a board category. Returns
    {category_name, on_catalog}: the canonical GBP category when the text
    resolves to one (on_catalog=True), else the cleaned typed text as an
    off-catalog service (on_catalog=False) that still grades live."""
    from services.leadoff_finder import resolve_category
    cleaned = " ".join((service or "").split()).strip()
    match = resolve_category(cleaned, board_categories) if cleaned else None
    if match:
        return {"category_name": match, "on_catalog": True}
    return {"category_name": cleaned, "on_catalog": False}


def cache_key(city_id: int, category_name: str) -> str:
    """Freshness key for the grade cache — city + normalized service name, so a
    typed 'Roofing' and 'roofing contractor' that resolve to the same category
    share a cache row."""
    return f"{int(city_id)}|{norm(category_name)}"


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


def build_grade_row(*, category_name: str, category_id: Optional[str],
                    vol: Optional[float], cpc: Optional[float],
                    field: dict[str, Any], cpl: float, cpl_default: bool,
                    breakpoints: list[float], capture: float,
                    competitors: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Compose the single grade row from measured demand + a SERP field read,
    reusing the tryout's economics/grade math (one category in, one row out).
    Pure — no I/O."""
    rows = la.tryout_rows(
        demand={category_name: {"vol": vol, "cpc": cpc}},
        field={category_name: field},
        cpl={category_name: cpl},
        breakpoints=breakpoints,
        capture=capture,
    )
    row = rows[0] if rows else {"category": category_name, "grade": "F", "exp_val": 0}
    row["category_id"] = category_id
    row["thin_demand"] = thin_demand(vol)
    row["cpl"] = round(float(cpl), 2)
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

def enqueue_grade(user_id: str, city_row: dict[str, Any], category_name: str,
                  category_id: Optional[str], on_catalog: bool,
                  service_query: str, capture: float,
                  lead_tier: str) -> dict[str, Any]:
    """Create the leadoff_grades row (status running) + the async job that
    fills it. Poll GET /leadoff/grade/{grade_id}."""
    supabase = get_supabase()
    grade = supabase.table("leadoff_grades").insert({
        "requested_by": user_id,
        "city_id": city_row.get("city_id"),
        "city_name": city_row.get("name"),
        "state_code": city_row.get("state_code"),
        "category_id": category_id,
        "category_name": category_name,
        "service_query": service_query,
        "cache_key": cache_key(city_row.get("city_id"), category_name),
        "capture": capture, "lead_tier": lead_tier,
        "on_catalog": on_catalog, "source": "live", "status": "running",
    }).execute().data[0]
    job = supabase.table("async_jobs").insert({
        "job_type": "leadoff_grade",
        "entity_id": grade["id"],
        "payload": {"grade_id": grade["id"], "city_id": city_row.get("city_id"),
                    "category_name": category_name, "category_id": category_id,
                    "capture": capture, "lead_tier": lead_tier},
    }).execute().data[0]
    return {"grade": grade, "grade_id": grade["id"], "job_id": job["id"]}


async def run_grade_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    grade_id = payload.get("grade_id")
    category_name = payload.get("category_name") or ""
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
                      "keywords": [category_name, category_name + " near me"]}])
                task = la._task0(posted)
                la._check_money_limit(task)
                result = await la._poll_task(
                    client, "/keywords_data/google_ads/search_volume/task_get",
                    task.get("id"), interval_s=8, attempts=45)
                dem = la.demand_from_items(result or [], [category_name])
                vol = dem.get(category_name, {}).get("vol")
                cpc = dem.get(category_name, {}).get("cpc")

            # 2) one Maps SERP live @ 13z (lesson #1); 40102 = a VALID zero
            from services.leadoff_brand import top5_from_items
            coord = f"{city['latitude']},{city['longitude']},13z"
            d = await la._dfs_post(
                client, "/serp/google/maps/live/advanced",
                [{"keyword": category_name, "location_coordinate": coord,
                  "language_code": "en", "device": "desktop", "os": "windows",
                  "depth": 100}])
            t0 = la._task0(d)
            la._check_money_limit(t0)
            if t0.get("status_code") == la._CODE_NO_RESULTS:
                items: list[dict[str, Any]] = []
            else:
                items = ((t0.get("result") or [{}])[0] or {}).get("items") or []
            field = la.field_stats(items, category_name)
            competitors = top5_from_items(items)

        # 3) economics + grade vs the national reference
        cpl, cpl_default = resolve_cpl(
            category_name, la._lead_values(lead_tier),
            __import__("config").settings.leadoff_finder_default_lead_value)
        row = build_grade_row(
            category_name=category_name, category_id=category_id,
            vol=vol, cpc=cpc, field=field, cpl=cpl, cpl_default=cpl_default,
            breakpoints=la._breakpoints(), capture=capture,
            competitors=competitors)
        try:
            from services.leadoff_beatability import attach_beatability
            from services.leadoff_roi import attach_roi
            row = [attach_roi(r) for r in attach_beatability([row])][0]
        except Exception:
            logger.warning("leadoff_grade.enrich_failed", exc_info=True)

        supabase.table("leadoff_grades").update({
            "status": "complete", "grade": row, "cpl_default": cpl_default,
            "pulled_at": now.isoformat(), "completed_at": "now()",
        }).eq("id", grade_id).execute()
        supabase.table("async_jobs").update({
            "status": "complete", "completed_at": "now()",
            "result": {"grade": row.get("grade"), "exp_val": row.get("exp_val")},
        }).eq("id", job_id).execute()
        logger.info("leadoff_grade.complete", extra={
            "grade_id": grade_id, "category": category_name,
            "grade": row.get("grade"), "thin_demand": row.get("thin_demand")})
    except Exception as exc:
        logger.error("leadoff_grade.failed",
                     extra={"job_id": job_id, "error": str(exc)})
        _fail(str(exc))
