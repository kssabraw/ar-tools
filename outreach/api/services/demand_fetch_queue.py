"""The signed-order drain for the valuation's DEMAND signal: a scan finalize → one paid search-volume
fetch, cached into keyword_demand.

Direct sibling of `organic_scan_queue`, and narrow for the same load-bearing reasons documented
there: ONE order per tick, a failed order is terminal, claims are conditional, the budget gate runs
before the money. The demand fetch is idempotent at the CACHE level — a (keyword, location_token)
already fetched fresh drains as a free `done` no-op (`fetch_demand.already_cached`) — so a re-order,
or a second submarket in the same city, never re-bills.

Auto-enqueued on scan finalize (owner-flagged, `demand_auto_enabled`) beside the organic order, with
a sentinel `requested_by` so an auto fetch stays auditable apart from a UI click.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import demand_fetch

logger = logging.getLogger(__name__)


@dataclass
class DemandDrainReport:
    """What one tick's demand drain did. Everything is also on the ORDER ROW — this is the log copy."""

    claimed: int = 0            # 0 or 1 by construction
    order_id: str = ""
    snapshot_id: str = ""
    keyword: str = ""
    location_token: str = ""
    outcome: str = "idle"       # idle | done | failed
    already_cached: bool = False
    search_volume: int | None = None
    error: str = ""
    problems: list[str] = field(default_factory=list)


def estimate_cost_cents(per_request_cents: int) -> int:
    """One DataForSEO search-volume request."""
    return max(0, per_request_cents)


def budget_denial(estimate_cents: int, max_run_cost_cents: int) -> str | None:
    """Why an order may NOT run, or None. Mirrors organic_scan_queue.budget_denial."""
    if estimate_cents > max_run_cost_cents:
        return (
            f"estimated cost {estimate_cents}¢ exceeds max_market_run_cost_cents "
            f"{max_run_cost_cents}¢ — order refused before anything was posted"
        )
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_AUTO_NOTE = "auto: demand (search volume + CPC) for the missed-opportunity valuation"


def enqueue_for_snapshot(db: Any, settings: Settings, snapshot_id: str) -> bool:
    """Auto-place a signed demand order for a just-finalized snapshot. Returns True iff a NEW order
    was placed. Gated on `demand_auto_enabled`; best-effort (never raises); idempotent.

    Two idempotency guards: (1) any prior demand order for this snapshot → already handled; (2) a
    keyword_demand row already fresh for this snapshot's (keyword, submarket location_token) →
    nothing to fetch, so don't even enqueue a no-op order (this is what keeps a dozen submarkets in
    the same city from each churning an order the drain would only no-op). The drain still cache-
    checks, so guard (2) missing a case is harmless."""
    try:
        if not settings.demand_auto_enabled:
            return False
        snap = (
            db.table("scan_snapshot").select("id, keyword_id, submarket_id")
            .eq("id", snapshot_id).limit(1).execute().data or []
        )
        if not snap or not snap[0].get("keyword_id"):
            return False
        keyword_id = snap[0]["keyword_id"]
        submarket_id = snap[0].get("submarket_id")

        # Guard 1: a prior order for this snapshot (any status).
        if (
            db.table("demand_fetch_request").select("id")
            .eq("snapshot_id", snapshot_id).limit(1).execute().data or []
        ):
            return False

        # Guard 2 (best-effort): the (keyword, location_token) is already cached fresh.
        kw = (
            db.table("keyword").select("term").eq("id", keyword_id).limit(1).execute().data or []
        )
        token = ""
        if submarket_id:
            sub = (
                db.table("submarket").select("location_token")
                .eq("id", submarket_id).limit(1).execute().data or []
            )
            token = str((sub[0].get("location_token") if sub else "") or "").strip()
        if kw and token:
            kw_key = demand_fetch.normalize_keyword(str(kw[0].get("term") or ""))
            cached = (
                db.table("keyword_demand").select("fetched_at")
                .eq("keyword", kw_key).eq("location_token", token).limit(1).execute().data or []
            )
            if cached and demand_fetch.is_cache_fresh(
                cached[0].get("fetched_at"), settings.demand_refresh_days,
                datetime.now(timezone.utc),
            ):
                return False

        db.table("demand_fetch_request").insert({
            "snapshot_id": snapshot_id,
            "keyword_id": keyword_id,
            "requested_by": settings.demand_auto_actor_id,
            "note": _AUTO_NOTE,
        }).execute()
        logger.info("auto-enqueued demand order", extra={"snapshot_id": snapshot_id})
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort; the one-active index also rejects a race
        logger.warning("auto demand enqueue skipped",
                       extra={"snapshot_id": snapshot_id, "error": str(exc)[:200]})
        return False


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending order, claimed, or None. Read-then-conditionally-claim."""
    rows = (
        db.table("demand_fetch_request").select("*")
        .eq("status", "pending").order("created_at", desc=False).limit(1).execute().data or []
    )
    if not rows:
        return None
    order = rows[0]
    claimed = (
        db.table("demand_fetch_request")
        .update({"status": "running", "started_at": _now()})
        .eq("id", order["id"]).eq("status", "pending").execute().data or []
    )
    return dict(order, status="running") if claimed else None


def _finish(db: Any, order_id: str, fields: dict[str, Any]) -> None:
    db.table("demand_fetch_request").update(dict(fields, finished_at=_now())).eq(
        "id", order_id
    ).execute()


async def drain_one(db: Any, settings: Settings) -> DemandDrainReport:
    """Claim and execute at most one demand order. Never raises past recording the failure."""
    report = DemandDrainReport()
    order = claim_next_order(db)
    if order is None:
        return report

    report.claimed = 1
    report.order_id = str(order["id"])

    snapshot_rows = (
        db.table("scan_snapshot").select("id, submarket_id, keyword_id")
        .eq("id", order["snapshot_id"]).limit(1).execute().data
    )
    keyword_rows = (
        db.table("keyword").select("id, term").eq("id", order["keyword_id"]).limit(1).execute().data
    )
    if not snapshot_rows or not keyword_rows:
        report.outcome = "failed"
        report.error = "snapshot or keyword no longer exists"
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        return report

    snapshot = snapshot_rows[0]
    keyword_term = str(keyword_rows[0].get("term") or "")
    report.snapshot_id = str(snapshot["id"])
    report.keyword = keyword_term

    estimate = estimate_cost_cents(settings.dataforseo_cost_per_request_cents)
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial})
        return report

    # market_id for the cost_ledger row: snapshot → submarket → market. Best-effort.
    market_id: str | None = None
    submarket_id = snapshot.get("submarket_id")
    if submarket_id:
        sub = (
            db.table("submarket").select("market_id").eq("id", submarket_id).limit(1).execute().data
        )
        if sub:
            market_id = sub[0].get("market_id")

    try:
        result = await demand_fetch.fetch_demand(
            db, settings, snapshot, keyword_term, market_id=market_id
        )
    except Exception as exc:  # noqa: BLE001 — the order must resolve; a stuck `running` row blocks
        # its (snapshot, keyword) pair forever via the one-active index.
        report.outcome = "failed"
        report.error = repr(exc)[:500]
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        logger.error("demand order failed in fetch", extra={"order_id": report.order_id})
        return report

    report.already_cached = bool(result.already_cached)
    report.location_token = result.location_token
    report.search_volume = result.search_volume
    report.problems = list(result.problems)

    if not (result.stored or result.already_cached):
        report.outcome = "failed"
        detail = "; ".join(result.problems) or "no result returned"
        report.error = f"demand fetch stored nothing: {detail}"
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        return report

    report.outcome = "done"
    _finish(db, report.order_id, {"status": "done", "error": None})
    logger.info(
        "demand order executed",
        extra={
            "order_id": report.order_id,
            "snapshot_id": report.snapshot_id,
            "already_cached": report.already_cached,
            "search_volume": report.search_volume,
        },
    )
    return report
