"""AI Visibility (Brand Strength) — keyword/competitor CRUD, scan dispatch,
history queries, and trend rollups. The scan engine itself lives in
`services/brand_scan.py`; this module is the API-facing business logic.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from db.supabase_client import get_supabase
from services.brand_scan import ENGINE_ORDER, ENGINES, enqueue_brand_scan

logger = logging.getLogger("brand_service")


def _safe(fn, *, error_code: str = "internal_error"):
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - thin DB-error wrapper
        logger.warning("brand_service.db_error", extra={"error": str(exc), "code": error_code})
        raise HTTPException(status_code=500, detail=error_code)


# ── keywords ─────────────────────────────────────────────────────────────────
def list_keywords(client_id: str, include_inactive: bool = True) -> list[dict]:
    def _q():
        q = (
            get_supabase().table("brand_tracked_keywords")
            .select("id, keyword, category, is_active, created_at")
            .eq("client_id", client_id)
        )
        if not include_inactive:
            q = q.eq("is_active", True)
        return q.order("created_at", desc=True).execute().data or []
    return _safe(_q)


def add_keyword(client_id: str, keyword: str, category: Optional[str]) -> dict:
    def _q():
        try:
            res = (
                get_supabase().table("brand_tracked_keywords")
                .insert({"client_id": client_id, "keyword": keyword.strip(), "category": category})
                .execute()
            )
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                raise HTTPException(status_code=409, detail="keyword_exists")
            raise
        return res.data[0]
    return _safe(_q)


def update_keyword(client_id: str, keyword_id: str, is_active: Optional[bool], category: Optional[str]) -> dict:
    patch: dict = {"updated_at": "now()"}
    if is_active is not None:
        patch["is_active"] = is_active
    if category is not None:
        patch["category"] = category

    def _q():
        res = (
            get_supabase().table("brand_tracked_keywords")
            .update(patch)
            .eq("id", keyword_id)
            .eq("client_id", client_id)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail="keyword_not_found")
        return res.data[0]
    return _safe(_q)


def delete_keyword(client_id: str, keyword_id: str) -> None:
    def _q():
        (
            get_supabase().table("brand_tracked_keywords")
            .delete()
            .eq("id", keyword_id)
            .eq("client_id", client_id)
            .execute()
        )
    _safe(_q)


# ── competitors ──────────────────────────────────────────────────────────────
def list_competitors(client_id: str) -> list[dict]:
    def _q():
        return (
            get_supabase().table("brand_tracked_competitors")
            .select("id, competitor_name, competitor_website, google_place_id, created_at")
            .eq("client_id", client_id)
            .order("created_at", desc=True)
            .execute().data or []
        )
    return _safe(_q)


def add_competitor(client_id: str, name: str, website: Optional[str], place_id: Optional[str]) -> dict:
    def _q():
        try:
            res = (
                get_supabase().table("brand_tracked_competitors")
                .insert({
                    "client_id": client_id, "competitor_name": name.strip(),
                    "competitor_website": website, "google_place_id": place_id,
                })
                .execute()
            )
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                raise HTTPException(status_code=409, detail="competitor_exists")
            raise
        return res.data[0]
    return _safe(_q)


def delete_competitor(client_id: str, competitor_id: str) -> None:
    def _q():
        (
            get_supabase().table("brand_tracked_competitors")
            .delete()
            .eq("id", competitor_id)
            .eq("client_id", client_id)
            .execute()
        )
    _safe(_q)


# ── scans ────────────────────────────────────────────────────────────────────
def start_scan(
    client_id: str,
    keyword_ids: Optional[list[str]],
    engines: Optional[list[str]],
    include_competitors: bool,
    user_id: Optional[str],
) -> dict:
    """Resolve defaults (all active keywords / all six engines) then enqueue a job."""
    if engines is None:
        engines = list(ENGINE_ORDER)
    else:
        bad = [e for e in engines if e not in ENGINES]
        if bad:
            raise HTTPException(status_code=400, detail="invalid_engine")

    if keyword_ids is None:
        active = [k["id"] for k in list_keywords(client_id, include_inactive=False)]
        keyword_ids = active
    if not keyword_ids:
        raise HTTPException(status_code=400, detail="no_keywords_to_scan")

    return enqueue_brand_scan(client_id, keyword_ids, engines, include_competitors, user_id)


def get_scan_status(client_id: str, job_id: str) -> dict:
    def _q():
        res = (
            get_supabase().table("async_jobs")
            .select("status, result, error, entity_id, job_type")
            .eq("id", job_id)
            .limit(1)
            .execute().data
        )
        if not res or res[0].get("entity_id") != client_id or res[0].get("job_type") != "brand_scan":
            raise HTTPException(status_code=404, detail="scan_not_found")
        row = res[0]
        result = row.get("result") or {}
        return {
            "status": row["status"],
            "total": result.get("total", 0),
            "completed": result.get("completed", 0),
            "failed": result.get("failed", 0),
            "scan_batch_id": result.get("scan_batch_id"),
            "error": row.get("error"),
        }
    return _safe(_q)


# ── history / trends ─────────────────────────────────────────────────────────
_HISTORY_COLS = (
    "id, keyword_id, scan_batch_id, engine, status, mention_found, mention_type, "
    "sentiment, confidence_score, citations, competitor_results, reasoning, snippet, "
    "invisibility_diagnosis, response_analysis, failure_reason, created_at"
)


def list_history(
    client_id: str,
    limit: int = 200,
    engine: Optional[str] = None,
    keyword_id: Optional[str] = None,
    scan_batch_id: Optional[str] = None,
) -> list[dict]:
    def _q():
        q = (
            get_supabase().table("brand_mention_history")
            .select(_HISTORY_COLS)
            .eq("client_id", client_id)
            .eq("is_competitor_scan", False)
        )
        if engine:
            q = q.eq("engine", engine)
        if keyword_id:
            q = q.eq("keyword_id", keyword_id)
        if scan_batch_id:
            q = q.eq("scan_batch_id", scan_batch_id)
        return q.order("created_at", desc=True).limit(limit).execute().data or []
    return _safe(_q)


def compute_trends(rows: list[dict]) -> list[dict]:
    """Roll completed brand-mention rows up by scan batch → per-engine + overall
    visibility. Pure (no DB) so it can be unit-tested. Newest batch last."""
    batches: dict[str, dict] = {}
    for r in rows:
        if r.get("status") != "completed":
            continue
        batch = r.get("scan_batch_id") or "_"
        b = batches.setdefault(batch, {
            "scan_batch_id": r.get("scan_batch_id"),
            "created_at": r.get("created_at"),
            "engines": {},
            "total": 0,
            "found": 0,
        })
        # Earliest created_at in the batch represents the scan's time.
        if r.get("created_at") and (b["created_at"] is None or r["created_at"] < b["created_at"]):
            b["created_at"] = r["created_at"]
        eng = b["engines"].setdefault(r["engine"], {"total": 0, "found": 0})
        eng["total"] += 1
        b["total"] += 1
        if r.get("mention_found"):
            eng["found"] += 1
            b["found"] += 1

    def _pct(found, total):
        return round(100.0 * found / total, 1) if total else 0.0

    out = []
    for b in batches.values():
        engines = {
            e: {"total": v["total"], "found": v["found"], "visibility_pct": _pct(v["found"], v["total"])}
            for e, v in b["engines"].items()
        }
        out.append({
            "scan_batch_id": b["scan_batch_id"],
            "created_at": b["created_at"],
            "total": b["total"],
            "found": b["found"],
            "visibility_pct": _pct(b["found"], b["total"]),
            "engines": engines,
        })
    out.sort(key=lambda x: (x["created_at"] or ""))
    return out


async def get_keyword_market(client_id: str) -> dict:
    """CPC / search volume / competition for the client's active brand keywords,
    powering the Lead Valuation card. Cache-only read of the rank tracker's
    cross-client keyword_market table — the paid DataForSEO fill runs as the
    shared keyword_market async job (scope='brand'), auto-enqueued here when
    keywords are missing/stale, so a dashboard GET never blocks on (or pays
    for) a live provider call. `refreshing` is True while a fill job is
    pending/running; the card polls until it clears."""
    from datetime import datetime, timedelta, timezone

    from config import settings
    from services.dataforseo_rank import location_code_for
    from services.keyword_market import (
        enqueue_keyword_market, fetch_cached_market, market_job_pending, stale_keywords,
    )

    supabase = get_supabase()
    client_res = _safe(lambda: (
        supabase.table("clients").select("id, website_url, gbp, rank_tracking_location_code")
        .eq("id", client_id).limit(1).execute()
    ))
    if not client_res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    location_code = location_code_for(client_res.data[0])

    kw_list = [k["keyword"] for k in list_keywords(client_id, include_inactive=False)]
    if not kw_list:
        return {"location_code": location_code, "degraded": None, "refreshing": False, "keywords": []}

    cached = _safe(lambda: fetch_cached_market(supabase, kw_list, location_code))
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.keyword_market_refresh_days)
    to_fetch = stale_keywords(kw_list, cached, stale_cutoff)

    degraded: Optional[str] = None
    refreshing = _safe(lambda: market_job_pending(supabase, client_id, "brand"))
    if to_fetch and not refreshing:
        if not (settings.dataforseo_login and settings.dataforseo_password):
            degraded = "dataforseo_not_configured"
        else:
            _safe(lambda: enqueue_keyword_market(client_id, scope="brand"))
            refreshing = True

    return {
        "location_code": location_code,
        "degraded": degraded,
        "refreshing": refreshing,
        "keywords": [
            {
                "keyword": kw,
                "search_volume": cached.get(kw.lower(), {}).get("search_volume"),
                "cpc": cached.get(kw.lower(), {}).get("cpc"),
                "competition": cached.get(kw.lower(), {}).get("competition"),
            }
            for kw in kw_list
        ],
    }


def refresh_keyword_market(client_id: str) -> dict:
    """User-triggered market refresh: force-enqueue the scope='brand' job so
    even null-cached keywords (which the staleness pass treats as fresh for
    keyword_market_refresh_days) are re-queried."""
    from config import settings
    from services.keyword_market import enqueue_keyword_market

    if not (settings.dataforseo_login and settings.dataforseo_password):
        return {"refreshing": False, "degraded": "dataforseo_not_configured"}
    _safe(lambda: enqueue_keyword_market(client_id, scope="brand", force=True))
    return {"refreshing": True, "degraded": None}


def get_mention(client_id: str, mention_id: str) -> dict:
    """One mention row incl. the heavy fields (raw_response, retry_count) the
    history list deliberately omits — fetched lazily by the detail sheet."""
    def _q():
        rows = (
            get_supabase().table("brand_mention_history")
            .select(_HISTORY_COLS + ", raw_response, retry_count")
            .eq("id", mention_id)
            .eq("client_id", client_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            raise HTTPException(status_code=404, detail="mention_not_found")
        return rows[0]
    return _safe(_q)


def get_trends(client_id: str, limit: int = 2000) -> list[dict]:
    rows = list_history(client_id, limit=limit)
    return compute_trends(rows)


def aggregate_response_analysis(rows: list[dict]) -> dict:
    """Roll the per-cell response_analysis blobs of one scan batch into batch-wide
    insights: cross-engine consensus on which businesses the engines surface, the
    de-duplicated discovered (untracked) competitors, an AIO mention-kind tally,
    and a source-type tally. Pure (no DB) so it's unit-testable."""
    from services import brand_analysis

    brand_rows = [r for r in rows if not r.get("is_competitor_scan")]
    consensus = brand_analysis.consensus_rollup(brand_rows, brand="")

    discovered: dict[str, dict] = {}
    aio_kinds: dict[str, int] = {}
    source_types: dict[str, int] = {}
    for r in brand_rows:
        if r.get("status") != "completed":
            continue
        ra = r.get("response_analysis") or {}
        for d in ra.get("discovered_competitors") or []:
            name = (d.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            entry = discovered.setdefault(key, {"name": name, "engines": set(), "attributes": []})
            if r.get("engine"):
                entry["engines"].add(r["engine"])
            for a in d.get("attributes") or []:
                if a and a not in entry["attributes"]:
                    entry["attributes"].append(a)
        aio = ra.get("aio") or {}
        kind = aio.get("mention_kind")
        if kind:
            aio_kinds[kind] = aio_kinds.get(kind, 0) + 1
        for t, n in (ra.get("sources") or {}).get("by_type", {}).items():
            source_types[t] = source_types.get(t, 0) + n

    discovered_list = [
        {"name": v["name"], "engines": sorted(v["engines"]), "count": len(v["engines"]),
         "attributes": v["attributes"][:6]}
        for v in discovered.values()
    ]
    discovered_list.sort(key=lambda d: (-d["count"], d["name"].lower()))
    return {
        "consensus": consensus,
        "discovered_competitors": discovered_list,
        "aio_mention_kinds": aio_kinds,
        "source_types": source_types,
    }


def get_scan_insights(client_id: str, scan_batch_id: str) -> dict:
    """Batch-wide response-analysis insights for one scan (consensus, discovered
    competitors, AIO mention-kind + source-type tallies)."""
    rows = list_history(client_id, limit=1000, scan_batch_id=scan_batch_id)
    return aggregate_response_analysis(rows)


# ── insights (diagnose / suggest) ────────────────────────────────────────────
async def diagnose_mention(client_id: str, mention_id: str) -> dict:
    """Explain why the brand was invisible for a given not-found scan result.
    Caches the diagnosis on the row so re-asking is free."""
    from services import brand_insights

    supabase = get_supabase()
    rows = (
        supabase.table("brand_mention_history")
        .select("id, client_id, keyword_id, status, mention_found, scanned_brand_name, "
                "raw_response, invisibility_diagnosis")
        .eq("id", mention_id).limit(1).execute().data
    )
    if not rows or rows[0].get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="mention_not_found")
    row = rows[0]
    if row.get("invisibility_diagnosis"):
        return {"diagnosis": row["invisibility_diagnosis"], "cached": True}
    if row.get("status") != "completed" or row.get("mention_found"):
        raise HTTPException(status_code=400, detail="diagnosis_only_for_not_found")

    brand = row.get("scanned_brand_name") or ""
    keyword = ""
    if row.get("keyword_id"):
        kw = (
            supabase.table("brand_tracked_keywords").select("keyword")
            .eq("id", row["keyword_id"]).limit(1).execute().data
        )
        keyword = kw[0]["keyword"] if kw else ""
    try:
        block = await brand_insights.build_signals_block(client_id, keyword)
        diagnosis = await brand_insights.diagnose_invisibility(
            brand, keyword, row.get("raw_response") or "", block
        )
    except brand_insights.InsightUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    supabase.table("brand_mention_history").update(
        {"invisibility_diagnosis": diagnosis, "updated_at": "now()"}
    ).eq("id", mention_id).execute()
    return {"diagnosis": diagnosis, "cached": False}


def get_report_status(client_id: str, job_id: str) -> dict:
    def _q():
        res = (
            get_supabase().table("async_jobs")
            .select("status, result, error, entity_id, job_type")
            .eq("id", job_id).limit(1).execute().data
        )
        if not res or res[0].get("entity_id") != client_id or res[0].get("job_type") != "brand_report":
            raise HTTPException(status_code=404, detail="report_not_found")
        row = res[0]
        result = row.get("result") or {}
        return {"status": row["status"], "doc_url": result.get("doc_url"), "error": row.get("error")}
    return _safe(_q)


def _gather_tracked_keywords(supabase, client_id: str) -> list[str]:
    """Distinct active keywords the client already tracks across both rank
    trackers: organic (tracked_keywords, via its gsc_properties) + geo-grid
    (maps_keywords). Case-insensitive de-dupe, original casing preserved,
    capped at brand_suggest_max_seed_keywords. Best-effort per source."""
    from config import settings

    seeds: list[str] = []
    seen: set[str] = set()

    def _add(keyword: Optional[str]) -> None:
        kw = (keyword or "").strip()
        if kw and kw.lower() not in seen:
            seen.add(kw.lower())
            seeds.append(kw)

    # Organic — tracked_keywords is keyed to gsc_properties, not the client.
    try:
        props = (
            supabase.table("gsc_properties").select("id")
            .eq("client_id", client_id).execute().data
        ) or []
        prop_ids = [p["id"] for p in props if p.get("id")]
        if prop_ids:
            org = (
                supabase.table("tracked_keywords").select("keyword")
                .in_("property_id", prop_ids).eq("active", True).execute().data
            ) or []
            for r in org:
                _add(r.get("keyword"))
    except Exception:  # pragma: no cover - best-effort
        pass

    # Geo-grid — maps_keywords is keyed directly to the client.
    try:
        maps = (
            supabase.table("maps_keywords").select("keyword")
            .eq("client_id", client_id).eq("active", True).execute().data
        ) or []
        for r in maps:
            _add(r.get("keyword"))
    except Exception:  # pragma: no cover - best-effort
        pass

    return seeds[: settings.brand_suggest_max_seed_keywords]


def _business_context(client: dict) -> str:
    """A short business descriptor for grounding the conversational queries when
    (or alongside) the ICP: name + GBP primary category + location."""
    gbp = client.get("gbp") or {}
    parts = [client.get("name") or ""]
    if gbp.get("gbp_category"):
        parts.append(f"({gbp['gbp_category']})")
    loc = gbp.get("address") or gbp.get("formatted_address")
    if loc:
        parts.append(f"— {loc}")
    return " ".join(p for p in parts if p).strip()


async def suggest_keywords_for_client(client_id: str) -> dict:
    """Suggest AI queries to track by expanding the client's already-tracked
    organic + geo-grid ranking keywords into ICP-grounded conversational queries
    (3-5 each). When the client tracks no keywords yet, fall back to the legacy
    GBP-seeded keyword suggester so the button is never empty-handed."""
    from services import brand_insights, icp_service

    supabase = get_supabase()
    rows = (
        supabase.table("clients")
        .select("name, website_url, gbp, detected_icp, differentiators, icp_text")
        .eq("id", client_id).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = rows[0]
    brand = client.get("name") or ""
    seeds = _gather_tracked_keywords(supabase, client_id)

    try:
        if seeds:
            keywords = await brand_insights.suggest_conversational_queries(
                brand=brand,
                business_context=_business_context(client),
                icp_text=icp_service.resolve_icp_text(client),
                seed_keywords=seeds,
            )
        else:
            # No tracked keywords to expand — fall back to GBP-seeded suggestions.
            gbp = client.get("gbp") or {}
            business_types = [t for t in [gbp.get("gbp_category")] if t]
            address = gbp.get("address") or gbp.get("formatted_address")
            keywords = await brand_insights.suggest_keywords(brand, business_types, address)
    except brand_insights.InsightUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"keywords": keywords}
