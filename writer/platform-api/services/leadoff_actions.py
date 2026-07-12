"""LeadOff paid actions (PRD §5 item 1) — tryout + scout, ported faithfully
from the external scanner's check_city.py / enrich_shortlist.py
(docs/reference/leadoff-scanner/ — the methodology authority).

Tryout (~$0.20, ~3 min): score ANY city on demand. Keyword task with BOTH
forms (base + "near me" — near-me dominates many markets, costs nothing extra
per-task) → vol≥20 demand gate → Maps SERP live at **13z** per gated category
(default viewport gives false zeros — scanner lesson #1) → rankability
(field review-strength + exact-category openness, with the Handyman rename /
Plumbing→Plumber aliases — lesson #3) → economics → grade vs the national
exp_val percentile reference.

Scout (~$0.10–1/market, cache-cheapened): the Pass-2 finalist signals for one
board market — competitor referring domains, field review velocity, 12-month
demand trend. Writes back to the SHARED market_scanner caches with the exact
contracts the PowerShell tool uses (biz_key = f"{norm(name)}|{city_id}",
trend_key = f"{city_id}|{norm(category_name)}", RD stored as RAW tool reads
(×10 only at display), pulled_at + 90-day freshness) — both tools read/write
the same rows, so these formats must never drift.

Task-status discipline (scanner lesson #2): envelope 20000 ≠ task success;
40203 = daily money limit (abort, never record); 40102 "No Search Results" =
a VALID zero (record supply 0).

Spend: every enqueue records its estimate to public.leadoff_spend; the
per-user daily budget guard (leadoff_daily_budget_usd) runs BEFORE enqueue.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from config import settings
from db.supabase_client import get_supabase
from services.leadoff import _norm as norm  # the scanner's norm() — shared
from services.leadoff import grade_for, percentile_of

logger = logging.getLogger(__name__)

# NOTE the /v3: the scanner scripts' paths ("/serp/…") are relative to their
# common.py client, which prefixes the API version — a verbatim path port
# without this 404s on the first call (caught live 2026-07-12, $0 spent).
_BASE_URL = "https://api.dataforseo.com/v3"
FRESH_DAYS = 90          # cache freshness window (scout miss detection)
MIN_VOL = 20             # tryout demand gate (max of both keyword forms)

# GBP category quirks discovered the hard way (scanner lesson #3):
ALIAS_LABEL = {"handyman": "handyman handywoman handyperson"}  # renamed by Google
ALIAS_TO = {"plumbing": "plumber"}       # not selectable; real category = Plumber
STOP = {"service", "services", "company", "contractor", "shop", "store",
        "supplier", "and", "the", "near", "me"}

# Cost estimates (recorded to the ledger; derived from the scanner's own
# printed estimates + per-task billing). These are planning numbers.
# Tryout now includes the brand-footprint pass (site: indexed counts +
# Content Analysis mention summaries for each gated category's top-5,
# deduped + cache-cheapened): base ~$0.20 + footprint worst-case ~$0.80
# (≈25 distinct fresh businesses × ~$0.032). Franchises/repeat pulls cost less.
COST_TRYOUT = 1.00                # whole tryout run incl. footprint (planning)
COST_RD_PER_DOMAIN = 0.005        # bulk_referring_domains, per miss
COST_VELOCITY_PER_BIZ = 0.0023    # reviews task depth 30, per miss
COST_TREND_TASK = 0.05            # one Google Ads keyword task (per-task billing)

# DataForSEO task status codes (lesson #2)
_CODE_OK = 20000
_CODE_MONEY_LIMIT = 40203
_CODE_NO_RESULTS = 40102


# ── Pure helpers (unit-tested in tests/test_leadoff_actions.py) ───────────────

def holder_label(category_name: str) -> str:
    """The normalized primary-category label exact-holders are counted
    against, alias-resolved (Handyman rename; Plumbing → Plumber)."""
    n = norm(category_name)
    return ALIAS_LABEL.get(n, ALIAS_TO.get(n, n))


def category_tokens(category_name: str) -> list[str]:
    """Name-keyword tokens for the namekw stat: first 6 chars of words len≥4
    that aren't field-generic stopwords."""
    return [t[:6] for t in re.findall(r"[a-z]+", category_name.lower())
            if t not in STOP and len(t) >= 4]


def demand_from_items(items: list[dict[str, Any]],
                      category_names: list[str]) -> dict[str, dict[str, Any]]:
    """{category: {vol, cpc}} from a both-forms keyword-task result — vol is
    max(base, near-me) per lesson #4; cpc prefers the base form."""
    base: dict[str, dict] = {}
    near: dict[str, dict] = {}
    for it in items or []:
        kw = (it.get("keyword") or "").lower()
        if kw.endswith(" near me"):
            near[kw[:-8].strip()] = it
        else:
            base[kw] = it
    out: dict[str, dict[str, Any]] = {}
    for c in category_names:
        b, n = base.get(c.lower(), {}), near.get(c.lower(), {})
        out[c] = {"vol": max(b.get("search_volume") or 0, n.get("search_volume") or 0),
                  "cpc": b.get("cpc") or n.get("cpc")}
    return out


def field_stats(items: list[dict[str, Any]], category_name: str) -> dict[str, Any]:
    """The per-category SERP field read (mirrors check_city.pull): supply,
    top-5 review avg / rev_win (3rd-highest) / rating / name-keyword count,
    exact-category holders over ALL items."""
    label = holder_label(category_name)
    holders = sum(1 for it in items if norm(it.get("category") or "") == label)
    top5 = items[:5]
    revs = sorted((((it.get("rating") or {}).get("votes_count") or 0) for it in top5),
                  reverse=True)
    ratings = [v for v in (((it.get("rating") or {}).get("value")) for it in top5)
               if v is not None]
    toks = category_tokens(category_name)
    return {
        "supply": len(items),
        "avg5": round(sum(revs) / len(revs), 1) if revs else 0,
        "rev_win": revs[min(2, len(revs) - 1)] if revs else 0,
        "rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
        "namekw": sum(1 for it in top5
                      if any(t in str(it.get("title", "")).lower() for t in toks)),
        "holders": holders,
    }


def tryout_rows(demand: dict[str, dict[str, Any]], field: dict[str, dict[str, Any]],
                cpl: dict[str, float], breakpoints: list[float],
                capture: float) -> list[dict[str, Any]]:
    """Economics + grade per measured category (mirrors check_city step 3).
    Note: tryout uses RAW observed volume (a single city can't be regressed
    to a category expectation), so grades are slightly optimistic for
    outlier-demand cities vs the board's xdemand — same as the source tool."""
    rows: list[dict[str, Any]] = []
    for cat, v in field.items():
        vol = demand.get(cat, {}).get("vol")
        leadval = cpl.get(cat)
        leads = round((vol or 0) * capture)
        value = leads * leadval if leadval is not None else None
        rankab = round(0.75 / (1 + v["avg5"] / 50) + 0.25 / (1 + v["holders"] / 5), 2)
        ev = round((value or 0) * rankab)
        grade, pct = grade_for(percentile_of(ev, breakpoints), leads, rankab, leadval)
        rows.append({
            "grade": grade, "natl_pct": pct, "exp_val": ev, "value_mo": value,
            "roi": round(ev / max(v["rev_win"], 10), 1), "rankab": rankab,
            "category": cat, "vol": vol, "supply": v["supply"],
            "rev_win": v["rev_win"], "rating": v["rating"],
            "namekw": v["namekw"], "exact_open": v["holders"],
        })
    rows.sort(key=lambda r: r["exp_val"], reverse=True)
    return rows


def velocity_row(timestamps: list[datetime], biz_key: str, item_count: int,
                 now: datetime) -> dict[str, Any]:
    """The business_reviews cache row from a depth-30 newest-first pull —
    EXACT contract of enrich_shortlist.vel(): last30/prior30 counts, newest
    date, capped = the 30-review window didn't even reach 60 days back."""
    d30, d60 = now - timedelta(days=30), now - timedelta(days=60)
    return {
        "biz_key": biz_key,
        "last30": sum(1 for d in timestamps if d >= d30),
        "prior30": sum(1 for d in timestamps if d60 <= d < d30),
        "newest": max(timestamps).date().isoformat() if timestamps else None,
        "capped": item_count >= 30 and bool(timestamps) and min(timestamps) >= d60,
        "pulled_at": now.isoformat(),
    }


# Trend pulls now request this much history so the same-month YoY can be
# computed; the legacy fields keep slicing the most-recent 12, so their
# semantics are unchanged by the longer window.
TREND_MONTHS = 24


def trend_date_from(now: datetime) -> str:
    """First day of the month TREND_MONTHS back (Google Ads date_from)."""
    total = now.year * 12 + (now.month - 1) - TREND_MONTHS
    return f"{total // 12:04d}-{total % 12 + 1:02d}-01"


def same_month_growth(monthly: list[dict[str, Any]]) -> float | None:
    """Seasonality-cancelling growth (lesson #8's real fix): the 3 most recent
    months vs the SAME calendar months one year earlier, matched by
    (year, month). Refuses (None) when any of the 3 prior-year months is
    missing or the prior-year sum is zero — a partial match would reintroduce
    the seasonal confound this exists to remove. Pure."""
    by_ym = {(m.get("year"), m.get("month")): (m.get("search_volume") or 0)
             for m in monthly if m.get("year") is not None}
    if not by_ym:
        return None
    recent_keys = sorted(by_ym, reverse=True)[:3]
    if len(recent_keys) < 3:
        return None
    prior_keys = [(y - 1, mo) for y, mo in recent_keys]
    if any(k not in by_ym for k in prior_keys):
        return None
    recent, prior = sum(by_ym[k] for k in recent_keys), sum(by_ym[k] for k in prior_keys)
    return round(recent / prior, 2) if prior else None


def trend_row(monthly: list[dict[str, Any]], trend_key: str,
              now: datetime) -> dict[str, Any]:
    """The demand_trend cache row — the legacy fields keep the EXACT contract
    of enrich_shortlist (growth_yoy = recent-3 avg / oldest-3 avg over the
    most recent 12 entries — ⚠ seasonal-confounded, lesson #8, read with
    peak_months; peaks = top-2 volume months), and the COORDINATED ADDITIVE
    field growth_yoy_ss carries the same-month YoY (needs the 24-month pull;
    null on 12-month data — never a redefinition of growth_yoy)."""
    vals = [m.get("search_volume") or 0 for m in monthly][:12]
    if len(vals) >= 6:
        recent, old = sum(vals[:3]) / 3, sum(vals[-3:]) / 3
        growth = round(recent / old, 2) if old else None
        peaks = sorted(monthly[:12], key=lambda m: -(m.get("search_volume") or 0))[:2]
        peak = ",".join(str(m.get("month")) for m in peaks)
    else:
        growth, peak = None, None
    return {"trend_key": trend_key, "growth_yoy": growth,
            "growth_yoy_ss": same_month_growth(monthly),
            "peak_months": peak, "pulled_at": now.isoformat()}


def pick_monthly(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """kw → monthly_searches from a both-forms task result; the longer series
    wins when base and near-me both carry history (mirrors the script)."""
    monthly: dict[str, list] = {}
    for it in items or []:
        kw = (it.get("keyword") or "").lower().replace(" near me", "").strip()
        ms = it.get("monthly_searches") or []
        if ms and (kw not in monthly or len(ms) > len(monthly[kw])):
            monthly[kw] = ms
    return monthly


def parse_review_timestamps(items: list[dict[str, Any]]) -> list[datetime]:
    for_out: list[datetime] = []
    for it in items or []:
        try:
            for_out.append(datetime.fromisoformat(
                str(it.get("timestamp")).replace(" +00:00", "+00:00")))
        except Exception:
            continue
    return for_out


def scout_estimate(rd_misses: int, vel_misses: int, trend_miss: bool) -> float:
    return round(rd_misses * COST_RD_PER_DOMAIN
                 + vel_misses * COST_VELOCITY_PER_BIZ
                 + (COST_TREND_TASK if trend_miss else 0), 2)


def spent_today(rows: list[dict[str, Any]]) -> float:
    return round(sum(float(r.get("est_cost") or 0) for r in rows), 2)


# ── DataForSEO plumbing ────────────────────────────────────────────────────────

def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    return {"Authorization": f"Basic {base64.b64encode(creds.encode()).decode()}",
            "Content-Type": "application/json"}


async def _dfs_post(client: httpx.AsyncClient, path: str, payload: list[dict]) -> dict:
    resp = await client.post(f"{_BASE_URL}{path}", headers=_auth_header(),
                             json=payload, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


async def _dfs_get(client: httpx.AsyncClient, path: str) -> dict:
    resp = await client.get(f"{_BASE_URL}{path}", headers=_auth_header(), timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def _task0(envelope: dict) -> dict:
    return (envelope.get("tasks") or [{}])[0]


def _check_money_limit(task: dict) -> None:
    if task.get("status_code") == _CODE_MONEY_LIMIT:
        raise RuntimeError("dataforseo_daily_limit")


async def _poll_task(client: httpx.AsyncClient, get_path: str, task_id: str,
                     interval_s: float, attempts: int) -> list | None:
    """Poll task_get until the task completes. Returns the result list, or
    None on timeout. Raises on the money-limit code (lesson #2)."""
    for _ in range(attempts):
        await asyncio.sleep(interval_s)
        got = await _dfs_get(client, f"{get_path}/{task_id}")
        t0 = _task0(got)
        _check_money_limit(t0)
        if t0.get("status_code") == _CODE_OK and t0.get("result") is not None:
            return t0["result"]
    return None


# ── Market-scanner reads (via the scoped client) ──────────────────────────────

def _ms(table: str):
    from services.leadoff_db import get_leadoff_client
    return get_leadoff_client().table(table)


def resolve_city(city: str, state: str) -> dict[str, Any] | None:
    """Find the city in market_scanner.cities (US places ≥10k pop): exact
    name match first, then contains; biggest population wins ties."""
    rows = (_ms("cities").select("*")
            .ilike("name", city.strip()).eq("state_code", state.strip().upper())
            .execute().data or [])
    if not rows:
        rows = (_ms("cities").select("*")
                .ilike("name", f"%{city.strip()}%")
                .eq("state_code", state.strip().upper())
                .execute().data or [])
    if not rows:
        return None
    return max(rows, key=lambda r: r.get("population") or 0)


def _location_code(city_row: dict[str, Any]) -> int | None:
    lc = city_row.get("location_code")
    try:
        return int(float(lc)) if lc not in (None, "", "nan") else None
    except (TypeError, ValueError):
        return None


def _categories() -> list[dict[str, Any]]:
    return _ms("categories").select("category_id,category_name").execute().data or []


def _lead_values(tier: str) -> dict[str, float]:
    col = {"low": "cpl_low", "mid": "cpl_mid", "high": "cpl_high"}[tier]
    rows = _ms("lead_values").select(f"category_name,{col}").execute().data or []
    return {r["category_name"]: r[col] for r in rows if r.get(col) is not None}


def _breakpoints() -> list[float]:
    rows = (_ms("exp_val_percentiles").select("pct,exp_val")
            .order("pct").execute().data or [])
    return [float(r["exp_val"]) for r in rows]


def _fresh_cutoff(now: datetime) -> str:
    return (now - timedelta(days=FRESH_DAYS)).isoformat()


# ── Budget guard + spend ledger ───────────────────────────────────────────────

def check_budget(user_id: str, est_cost: float) -> None:
    """Raise BudgetExceeded when today's (UTC) recorded spend + this action
    would cross the per-user daily budget."""
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                   microsecond=0)
    rows = (get_supabase().table("leadoff_spend").select("est_cost")
            .eq("user_id", user_id).gte("created_at", day_start.isoformat())
            .execute().data or [])
    if spent_today(rows) + est_cost > settings.leadoff_daily_budget_usd:
        raise BudgetExceeded(
            f"daily LeadOff budget ${settings.leadoff_daily_budget_usd:.2f} "
            f"would be exceeded (spent ${spent_today(rows):.2f} today)")


class BudgetExceeded(Exception):
    pass


def record_spend(user_id: str, action: str, est_cost: float, **market) -> None:
    get_supabase().table("leadoff_spend").insert({
        "user_id": user_id, "action": action, "est_cost": est_cost,
        **{k: v for k, v in market.items() if v is not None},
    }).execute()


# ── Tryout job ────────────────────────────────────────────────────────────────

def enqueue_tryout(user_id: str, city_row: dict[str, Any], capture: float,
                   lead_tier: str) -> dict[str, Any]:
    supabase = get_supabase()
    tryout = supabase.table("leadoff_tryouts").insert({
        "requested_by": user_id,
        "city_id": city_row.get("city_id"),
        "city_name": city_row.get("name"),
        "state_code": city_row.get("state_code"),
        "capture": capture, "lead_tier": lead_tier,
        "est_cost": COST_TRYOUT,
    }).execute().data[0]
    job = supabase.table("async_jobs").insert({
        "job_type": "leadoff_tryout",
        "entity_id": tryout["id"],
        "payload": {"tryout_id": tryout["id"], "city_id": city_row.get("city_id"),
                    "capture": capture, "lead_tier": lead_tier},
    }).execute().data[0]
    return {"tryout": tryout, "job_id": job["id"]}


async def run_tryout_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    tryout_id = payload.get("tryout_id")

    def _fail(err: str) -> None:
        supabase.table("leadoff_tryouts").update(
            {"status": "failed", "error": err[:500], "completed_at": "now()"}
        ).eq("id", tryout_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": err[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

    try:
        supabase.table("leadoff_tryouts").update({"status": "running"}) \
            .eq("id", tryout_id).execute()
        city = (_ms("cities").select("*")
                .eq("city_id", payload["city_id"]).limit(1).execute().data or [None])[0]
        if not city:
            _fail("city_not_found")
            return
        cats = _categories()
        names = [c["category_name"] for c in cats]
        capture = float(payload.get("capture") or 0.10)
        lead_tier = payload.get("lead_tier") or "mid"

        async with httpx.AsyncClient() as client:
            # 1) demand + CPC: ONE task, both keyword forms (lesson #4)
            demand: dict[str, dict[str, Any]] = {}
            lc = _location_code(city)
            if lc:
                posted = await _dfs_post(
                    client, "/keywords_data/google_ads/search_volume/task_post",
                    [{"location_code": lc, "language_name": "English",
                      "keywords": names + [n + " near me" for n in names]}])
                task = _task0(posted)
                _check_money_limit(task)
                result = await _poll_task(
                    client, "/keywords_data/google_ads/search_volume/task_get",
                    task.get("id"), interval_s=10, attempts=50)
                demand = demand_from_items(result or [], names)
                gated = [n for n in names if demand[n]["vol"] >= MIN_VOL]
            else:
                # no Google Ads location code — demand unavailable; pull
                # supply for everything (same degraded path as the script)
                gated = list(names)

            # 2) Maps SERP live at 13z per gated category (lesson #1)
            sem = asyncio.Semaphore(10)
            coord = f"{city['latitude']},{city['longitude']},13z"

            from services.leadoff_brand import top5_from_items

            async def pull(cat: str) -> tuple[str, dict | None, list[dict]]:
                async with sem:
                    try:
                        d = await _dfs_post(
                            client, "/serp/google/maps/live/advanced",
                            [{"keyword": cat, "location_coordinate": coord,
                              "language_code": "en", "device": "desktop",
                              "os": "windows", "depth": 100}])
                        t0 = _task0(d)
                        _check_money_limit(t0)
                        if t0.get("status_code") == _CODE_NO_RESULTS:
                            return cat, field_stats([], cat), []  # a VALID zero
                        items = ((t0.get("result") or [{}])[0] or {}).get("items") or []
                        return cat, field_stats(items, cat), top5_from_items(items)
                    except RuntimeError:
                        raise
                    except Exception as exc:
                        logger.warning("leadoff_tryout.serp_failed",
                                       extra={"category": cat, "error": str(exc)})
                        return cat, None, []

            results = await asyncio.gather(*(pull(c) for c in gated))
            field = {cat: stats for cat, stats, _ in results if stats is not None}
            top5_by_cat = {cat: top5 for cat, _, top5 in results}

            # brand footprint for the field (first-pass LIGHT tier): distinct
            # businesses across all gated categories, cache-missed pieces
            # only. Generic-named businesses get the search+locale-filter +
            # phone-NAP treatment (their bare-name count is untrustworthy);
            # the unlinked split is scout's deep tier, not paid here.
            from services.leadoff_brand import (
                attach_footprint, fetch_footprint, footprint_lookups,
                footprint_state,
            )
            all_biz = [{**b, "category_name": cat}
                       for cat, top5 in top5_by_cat.items() for b in top5]
            try:
                fp = footprint_state(all_biz, datetime.now(timezone.utc),
                                     city_name=city.get("name") or "",
                                     deep=False)
                if fp["site_misses"] or fp["mention_misses"]:
                    await fetch_footprint(client, fp["site_misses"],
                                          fp["mention_misses"],
                                          datetime.now(timezone.utc),
                                          city_name=city.get("name") or "",
                                          deep=False)
            except RuntimeError:
                raise
            except Exception as exc:
                logger.warning("leadoff_tryout.footprint_failed",
                               extra={"error": str(exc)})

        # 3) economics + grade vs the national reference
        rows = tryout_rows(demand, field, _lead_values(lead_tier),
                           _breakpoints(), capture)
        try:
            site_lookup, mention_rows = footprint_lookups(all_biz)
            rows = attach_footprint(
                rows, top5_by_cat, site_lookup,
                {k: r.get("citations") for k, r in mention_rows.items()})
        except Exception:
            logger.warning("leadoff_tryout.footprint_attach_failed", exc_info=True)
        supabase.table("leadoff_tryouts").update({
            "status": "complete", "results": rows, "completed_at": "now()",
        }).eq("id", tryout_id).execute()
        supabase.table("async_jobs").update({
            "status": "complete", "completed_at": "now()",
            "result": {"categories_measured": len(rows)},
        }).eq("id", job_id).execute()
        logger.info("leadoff_tryout.complete", extra={
            "tryout_id": tryout_id, "categories": len(rows)})
    except Exception as exc:
        logger.error("leadoff_tryout.failed", extra={"job_id": job_id, "error": str(exc)})
        _fail(str(exc))


# ── Scout job ─────────────────────────────────────────────────────────────────

def scout_market_state(city_id: int, category_id: str) -> dict[str, Any] | None:
    """The market's competitors + which enrichment pieces are cache-misses
    (90-day freshness) — drives both the cost estimate and the job itself."""
    board = (_ms("leadoff_board").select("city_id,category_id,category,city_name,state_code")
             .eq("city_id", city_id).eq("category_id", category_id)
             .limit(1).execute().data or [])
    if not board:
        return None
    comps = (_ms("serp_top5").select("rank_position,business_name,domain")
             .eq("city_id", city_id).eq("category_id", category_id)
             .order("rank_position").limit(5).execute().data or [])
    now = datetime.now(timezone.utc)
    cutoff = _fresh_cutoff(now)
    domains = sorted({str(c["domain"]).strip() for c in comps
                      if c.get("domain") and str(c["domain"]).strip()})
    fresh_rd = (_ms("domain_backlinks").select("domain")
                .in_("domain", domains).gte("pulled_at", cutoff)
                .execute().data or []) if domains else []
    rd_misses = [d for d in domains if d not in {r["domain"] for r in fresh_rd}]
    biz = {f"{norm(c.get('business_name') or '')}|{city_id}": c.get("business_name")
           for c in comps if (c.get("business_name") or "").strip()}
    fresh_vel = (_ms("business_reviews").select("biz_key")
                 .in_("biz_key", list(biz)).gte("pulled_at", cutoff)
                 .execute().data or []) if biz else []
    vel_misses = {k: v for k, v in biz.items()
                  if k not in {r["biz_key"] for r in fresh_vel}}
    trend_key = f"{city_id}|{norm(board[0].get('category') or '')}"
    fresh_trend = (_ms("demand_trend").select("trend_key")
                   .eq("trend_key", trend_key).gte("pulled_at", cutoff)
                   .execute().data or [])
    # brand footprint (site size + the three mention signals) — deep tier:
    # scout is Pass-2, so every brand gets the search/unlinked/NAP treatment
    from services.leadoff_brand import footprint_state
    footprint = footprint_state(
        [{**c, "category_name": board[0].get("category") or ""} for c in comps],
        now, city_name=board[0].get("city_name") or "", deep=True)
    return {
        "market": board[0], "competitors": comps,
        "rd_misses": rd_misses, "vel_misses": vel_misses,
        "trend_key": trend_key, "trend_miss": not fresh_trend,
        "site_misses": footprint["site_misses"],
        "mention_misses": footprint["mention_misses"],
        "est_cost": round(scout_estimate(len(rd_misses), len(vel_misses),
                                         not fresh_trend)
                          + footprint["est_cost"], 2),
    }


def enqueue_scout(user_id: str, city_id: int, category_id: str,
                  est_cost: float) -> dict[str, Any]:
    # entity_id is a uuid column — the market identity lives in the payload.
    # (The original f"{city_id}:{category_id}" here failed the insert, so no
    # scout had ever actually enqueued; caught in the first live validation.)
    job = get_supabase().table("async_jobs").insert({
        "job_type": "leadoff_scout",
        "entity_id": str(uuid.uuid4()),
        "payload": {"city_id": city_id, "category_id": category_id,
                    "user_id": user_id, "est_cost": est_cost},
    }).execute().data[0]
    return {"job_id": job["id"]}


async def run_scout_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    city_id = int(payload["city_id"])
    category_id = str(payload["category_id"])
    try:
        state = scout_market_state(city_id, category_id)
        if state is None:
            raise RuntimeError("market_not_found")
        city = (_ms("cities").select("*")
                .eq("city_id", city_id).limit(1).execute().data or [None])[0]
        now = datetime.now(timezone.utc)
        summary = {"rd_pulled": 0, "velocity_pulled": 0, "trend_pulled": 0,
                   "rd_cached": len([d for d in (state["competitors"] or [])
                                     if d.get("domain")]) - len(state["rd_misses"])}

        async with httpx.AsyncClient() as client:
            # RD — one bulk call covers all misses (≤5 domains per market)
            if state["rd_misses"]:
                d = await _dfs_post(client, "/backlinks/bulk_referring_domains/live",
                                    [{"targets": state["rd_misses"]}])
                t0 = _task0(d)
                _check_money_limit(t0)
                items = ((t0.get("result") or [{}])[0] or {}).get("items") or []
                rows = [{"domain": it.get("target"),
                         "referring_domains": it.get("referring_domains"),
                         "pulled_at": now.isoformat()}
                        for it in items if it.get("target")]
                if rows:
                    _ms("domain_backlinks").insert(rows).execute()
                    summary["rd_pulled"] = len(rows)

            # velocity — depth-30 newest-first reviews task per cache-miss
            # business (task_post → poll; lat/lng WITHOUT zoom, per the script)
            if state["vel_misses"] and city:
                sem = asyncio.Semaphore(5)
                coord = f"{city['latitude']},{city['longitude']}"

                async def vel(biz_key: str, name: str) -> dict | None:
                    async with sem:
                        try:
                            p = await _dfs_post(
                                client, "/business_data/google/reviews/task_post",
                                [{"keyword": name, "location_coordinate": coord,
                                  "language_code": "en", "depth": 30,
                                  "sort_by": "newest"}])
                            t0 = _task0(p)
                            _check_money_limit(t0)
                            result = await _poll_task(
                                client, "/business_data/google/reviews/task_get",
                                t0.get("id"), interval_s=8, attempts=40)
                            if result is None:
                                return None
                            items = ((result or [{}])[0] or {}).get("items") or []
                        except RuntimeError:
                            raise
                        except Exception as exc:
                            logger.warning("leadoff_scout.velocity_failed",
                                           extra={"biz": name, "error": str(exc)})
                            return None
                    return velocity_row(parse_review_timestamps(items), biz_key,
                                        len(items), now)

                vel_rows = [r for r in await asyncio.gather(
                    *(vel(k, v) for k, v in state["vel_misses"].items())) if r]
                if vel_rows:
                    _ms("business_reviews").insert(vel_rows).execute()
                    summary["velocity_pulled"] = len(vel_rows)

            # brand footprint (deep tier) — site: indexed counts + mentions/
            # unlinked/NAP for the top-5. serp_top5 never stored phones, so
            # one Maps SERP recovers them for the NAP queries (~$0.004).
            from services.leadoff_brand import fetch_footprint, fetch_top5_phones
            misses = state.get("mention_misses") or {}
            if state.get("site_misses") or misses:
                if misses and city and not any(v.get("phone")
                                               for v in misses.values()):
                    phones = await fetch_top5_phones(
                        client, state["market"].get("category") or "", city)
                    for k, v in misses.items():
                        v["phone"] = v.get("phone") or phones.get(k)
                pulled = await fetch_footprint(
                    client, state.get("site_misses") or [], misses, now,
                    city_name=state["market"].get("city_name") or "", deep=True)
                summary["site_pulled"] = pulled["sites"]
                summary["mentions_pulled"] = pulled["mentions"]

            # trend — one keyword task (both forms) for this category
            lc = _location_code(city or {})
            if state["trend_miss"] and lc:
                cat_name = state["market"].get("category") or ""
                p = await _dfs_post(
                    client, "/keywords_data/google_ads/search_volume/task_post",
                    [{"location_code": lc, "language_name": "English",
                      "keywords": [cat_name, cat_name + " near me"],
                      # 24 months so growth_yoy_ss (same-month YoY) computes;
                      # legacy fields still slice the most recent 12.
                      "date_from": trend_date_from(now)}])
                t0 = _task0(p)
                _check_money_limit(t0)
                result = await _poll_task(
                    client, "/keywords_data/google_ads/search_volume/task_get",
                    t0.get("id"), interval_s=10, attempts=40)
                monthly = pick_monthly(result or [])
                row = trend_row(monthly.get(cat_name.lower(), []),
                                state["trend_key"], now)
                _ms("demand_trend").insert([row]).execute()
                summary["trend_pulled"] = 1

        supabase.table("async_jobs").update({
            "status": "complete", "completed_at": "now()", "result": summary,
        }).eq("id", job_id).execute()
        logger.info("leadoff_scout.complete", extra={
            "city_id": city_id, "category_id": category_id, **summary})
    except Exception as exc:
        logger.error("leadoff_scout.failed", extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
