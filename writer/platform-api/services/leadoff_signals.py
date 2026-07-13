"""LeadOff market-signal precompute (score-enrichment increment 2).

The board grade wants the winnability signals (proximity, incumbent site/brand
pressure), not just the demand-side permit signal — but computing octant math +
footprint medians for every board row on each page load is too heavy. This job
precomputes them per market into public.leadoff_market_signals ($0 — pure math
on the geocoded pins + the footprint caches already captured), and the board
read joins the cache cheaply.

  * proximity_opportunity — board-wide (needs only the geocoded competitor pins)
  * site_pressure / brand_pressure — fill only where a scout has populated the
    footprint caches; absent elsewhere (graceful — the board grade then uses
    proximity + permits for those markets)

Reaper-safe: the whole competitor pin set is loaded once (paginated), grouped
in memory, and results upserted in chunks. Idempotent (PK upsert).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_PAGE = 1000
_UPSERT_CHUNK = 500


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def _median(vals: list[float]) -> float | None:
    vs = sorted(v for v in vals if v is not None)
    if not vs:
        return None
    n = len(vs)
    return vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2


def compute_market_signal(center: tuple[float, float] | None,
                          pins: list[dict[str, Any]],
                          site_by_domain: dict[str, Any],
                          mentions_by_key: dict[str, Any]) -> dict[str, Any] | None:
    """One market's cached signal row body from its pins + the footprint caches.
    Pure. None when there's no usable geographic data (no center / no pins)."""
    from services.leadoff_brand import brand_key
    from services.leadoff_proximity import build_proximity
    from services.leadoff_scoring import brand_pressure, site_pressure
    from config import settings

    prox_opp = None
    if center is not None and pins:
        result = build_proximity(
            center[0], center[1], pins,
            radius_miles=settings.leadoff_proximity_radius_miles,
            min_pins=settings.leadoff_proximity_min_pins,
            weak_frac=settings.leadoff_proximity_weak_frac)
        prox_opp = None if result.get("thin_data") else result.get("opportunity")

    pages = _median([site_by_domain.get((p.get("domain") or "").strip())
                     for p in pins if (p.get("domain") or "").strip()])
    mentions = _median([mentions_by_key.get(brand_key(p.get("business_name") or ""))
                        for p in pins if (p.get("business_name") or "").strip()])
    site_p = site_pressure(pages) if pages is not None else None
    brand_p = brand_pressure(mentions) if mentions is not None else None

    if prox_opp is None and site_p is None and brand_p is None:
        return None
    return {"proximity_opportunity": prox_opp, "site_pressure": site_p,
            "brand_pressure": brand_p, "pins": len(pins)}


# ── Data access ───────────────────────────────────────────────────────────────

def _city_centers() -> dict[int, tuple[float, float]]:
    from services.leadoff_db import get_leadoff_client
    client = get_leadoff_client()
    idx: dict[int, tuple[float, float]] = {}
    page = 0
    while True:
        chunk = (client.table("cities").select("city_id, latitude, longitude")
                 .range(page * _PAGE, page * _PAGE + _PAGE - 1).execute().data or [])
        for c in chunk:
            if c.get("latitude") is not None and c.get("longitude") is not None:
                idx[c["city_id"]] = (float(c["latitude"]), float(c["longitude"]))
        if len(chunk) < _PAGE:
            return idx
        page += 1


def _grouped_pins(supabase) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """All geocoded competitor pins grouped by (city_id, category_id)."""
    out: dict[tuple[int, str], list[dict[str, Any]]] = {}
    page = 0
    while True:
        chunk = (supabase.table("competitor_locations")
                 .select("city_id, category_id, business_name, domain, "
                         "review_count, lat, lng")
                 .not_.is_("lat", "null")
                 .range(page * _PAGE, page * _PAGE + _PAGE - 1).execute().data or [])
        for r in chunk:
            out.setdefault((r["city_id"], r["category_id"]), []).append(r)
        if len(chunk) < _PAGE:
            return out
        page += 1


def _footprint_caches(supabase) -> tuple[dict[str, Any], dict[str, Any]]:
    site: dict[str, Any] = {}
    page = 0
    while True:
        chunk = (supabase.table("domain_site_size").select("domain, indexed_pages")
                 .range(page * _PAGE, page * _PAGE + _PAGE - 1).execute().data or [])
        for r in chunk:
            site[r["domain"]] = r.get("indexed_pages")
        if len(chunk) < _PAGE:
            break
        page += 1
    mentions: dict[str, Any] = {}
    page = 0
    while True:
        chunk = (supabase.table("brand_mentions").select("brand_key, citations")
                 .range(page * _PAGE, page * _PAGE + _PAGE - 1).execute().data or [])
        for r in chunk:
            mentions[r["brand_key"]] = r.get("citations")
        if len(chunk) < _PAGE:
            break
        page += 1
    return site, mentions


def read_signals(supabase, markets: list[tuple[int, str]]) -> dict[tuple[int, str], dict]:
    """Cheap board-read: cached signal rows for the displayed markets. Fetches
    by the ≤N city_ids (composite-key .in_ is awkward in PostgREST) and matches
    category in memory."""
    if not markets:
        return {}
    city_ids = sorted({c for c, _ in markets})
    rows = (supabase.table("leadoff_market_signals")
            .select("city_id, category_id, proximity_opportunity, "
                    "site_pressure, brand_pressure")
            .in_("city_id", city_ids).execute().data or [])
    return {(r["city_id"], r["category_id"]): r for r in rows}


# ── Scheduling (self-gating: only enqueues when the cache is empty or stale) ──

def enqueue_due_signal_refresh() -> int:
    """Enqueue a refresh when the signal cache is empty or older than
    `leadoff_signal_refresh_days`, and no signal job is already queued. Returns
    the number enqueued (0 or 1). Cheap daily check; the compute lives in the
    job. Best-effort — never raises into the scheduler loop."""
    from datetime import timedelta

    from config import settings
    try:
        supabase = get_supabase()
        active = (supabase.table("async_jobs").select("id", count="exact")
                  .eq("job_type", "leadoff_signal_refresh")
                  .in_("status", ["pending", "running"]).limit(1)
                  .execute().count or 0)
        if active:
            return 0
        newest = (supabase.table("leadoff_market_signals")
                  .select("computed_at").order("computed_at", desc=True)
                  .limit(1).execute().data or [])
        if newest:
            age_cut = (datetime.now(timezone.utc)
                       - timedelta(days=settings.leadoff_signal_refresh_days))
            ts = datetime.fromisoformat(str(newest[0]["computed_at"]))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts > age_cut:
                return 0
        import uuid
        supabase.table("async_jobs").insert({
            "job_type": "leadoff_signal_refresh", "entity_id": str(uuid.uuid4()),
            "payload": {}, "max_attempts": 3}).execute()
        return 1
    except Exception:
        logger.warning("leadoff_signal_refresh.enqueue_failed", exc_info=True)
        return 0


# ── Job ───────────────────────────────────────────────────────────────────────

async def run_signal_refresh_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    try:
        centers = _city_centers()
        pins_by_market = _grouped_pins(supabase)
        site_by_domain, mentions_by_key = _footprint_caches(supabase)
        now = datetime.now(timezone.utc).isoformat()

        writes: list[dict[str, Any]] = []
        computed = 0
        for (city_id, category_id), pins in pins_by_market.items():
            body = compute_market_signal(centers.get(city_id), pins,
                                         site_by_domain, mentions_by_key)
            if body is None:
                continue
            writes.append({"city_id": city_id, "category_id": category_id,
                           **body, "computed_at": now})
            computed += 1
            if len(writes) >= _UPSERT_CHUNK:
                supabase.table("leadoff_market_signals").upsert(writes).execute()
                writes = []
        if writes:
            supabase.table("leadoff_market_signals").upsert(writes).execute()

        result = {"markets_with_pins": len(pins_by_market), "computed": computed,
                  "footprint_domains": len(site_by_domain),
                  "footprint_brands": len(mentions_by_key)}
        supabase.table("async_jobs").update({
            "status": "complete", "result": result, "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("leadoff_signal_refresh.complete", extra=result)
    except Exception as exc:
        logger.error("leadoff_signal_refresh.failed",
                     extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
