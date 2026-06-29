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
    "invisibility_diagnosis, failure_reason, created_at"
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


def get_trends(client_id: str, limit: int = 2000) -> list[dict]:
    rows = list_history(client_id, limit=limit)
    return compute_trends(rows)


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
        signals = brand_insights.gather_client_signals(client_id, keyword)
        block = brand_insights.format_signals_block(signals)
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


async def suggest_keywords_for_client(client_id: str) -> dict:
    """Suggest keywords to track, using the client's name + GBP business context."""
    from services import brand_insights

    supabase = get_supabase()
    rows = (
        supabase.table("clients").select("name, website_url, gbp")
        .eq("id", client_id).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = rows[0]
    gbp = client.get("gbp") or {}
    brand = client.get("name") or ""
    business_types = [t for t in [gbp.get("gbp_category")] if t]
    address = gbp.get("address") or gbp.get("formatted_address")
    try:
        keywords = await brand_insights.suggest_keywords(brand, business_types, address)
    except brand_insights.InsightUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"keywords": keywords}
