"""The onboard-order drain: a typed city becomes discover → filter → scan, on one signed order.

Sibling to `scan_queue`. Where that drain runs ONE scan of an already-ingested submarket, this one
runs the whole pipeline for a city that has never been ingested (ISSUES I-092): the paid Outscraper
`ingest` (the business type is the category), the free `filter`, then the geogrid `scan`. Same
one-order-per-tick, conditional-claim, budget-before-money, terminal-failure discipline as
`scan_queue` — the claim/budget primitives are reused, not re-derived.

The one genuinely new property is STAGED failure across a multi-stage paid run. `scan_queue` has a
single paid step; this has two (ingest, scan) with a free one between. So the order records which
STAGE it reached, and failure handling is layered:

  * A budget refusal, or an ingest refused by its own cost gate, fails the order with NOTHING spent.
  * An ingest/filter failure fails the order after discovery — money may have moved on the pull, so
    the ingested/survived counts are recorded, but no scan was opened.
  * A scan failure resolves the order from what actually happened, keeping `snapshot_id` findable
    (the paid-task bookkeeping hangs off it) — exactly `scan_queue`'s rule.

The order MUST always resolve: a row stuck `running` blocks its (submarket, keyword) pair forever
through the one-active index.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import scan_runner, seeding
from .cost import CostLimitExceeded
from .filters import resolve_accepted_categories
from .pipeline import run_filter, run_ingest
from .scan_queue import budget_denial, estimate_cost_cents

logger = logging.getLogger(__name__)

_TABLE = "onboard_request"


@dataclass
class OnboardDrainReport:
    """What one tick's onboard drain did — the log-line copy; the durable copy is the order row."""

    claimed: int = 0            # 0 or 1 by construction
    order_id: str = ""
    submarket: str = ""
    keyword: str = ""
    category: str = ""
    stage: str = ""             # ingest | filter | scan | done — where it got to
    outcome: str = "idle"       # idle | done | failed
    prospects_ingested: int = 0
    prospects_survived: int = 0
    snapshot_id: str = ""
    posted: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending onboard order, claimed, or None. Read-then-conditionally-claim: the
    update re-checks `status = 'pending'`, so a row claimed between read and write comes back empty
    and we drain nothing this tick (losing a race costs a tick; winning it twice costs a paid
    pull)."""
    rows = (
        db.table(_TABLE)
        .select("*")
        .eq("status", "pending")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    order = rows[0]
    claimed = (
        db.table(_TABLE)
        .update({"status": "running", "started_at": _now()})
        .eq("id", order["id"])
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    return dict(order, status="running") if claimed else None


def _update(db: Any, order_id: str, fields: dict[str, Any]) -> None:
    db.table(_TABLE).update(dict(fields)).eq("id", order_id).execute()


def _finish(db: Any, order_id: str, fields: dict[str, Any]) -> None:
    _update(db, order_id, dict(fields, finished_at=_now()))


def _fail(
    db: Any, report: OnboardDrainReport, error: str, *, snapshot_id: str | None = None
) -> OnboardDrainReport:
    report.outcome = "failed"
    report.error = error
    fields: dict[str, Any] = {
        "status": "failed",
        "error": error,
        "stage": report.stage or None,
        "prospects_ingested": report.prospects_ingested or None,
        "prospects_survived": report.prospects_survived or None,
    }
    if snapshot_id:
        fields["snapshot_id"] = snapshot_id
        report.snapshot_id = snapshot_id
    _finish(db, report.order_id, fields)
    return report


async def drain_one(db: Any, settings: Settings) -> OnboardDrainReport:
    """Claim and execute at most one onboard order — discover → filter → scan. Never raises past
    recording the failure."""
    report = OnboardDrainReport()
    order = claim_next_order(db)
    if order is None:
        return report

    report.claimed = 1
    report.order_id = str(order["id"])
    report.category = str(order.get("category") or "")

    submarket = (
        db.table("submarket").select("*").eq("id", order["submarket_id"]).limit(1).execute().data
    )
    keyword = (
        db.table("keyword").select("*").eq("id", order["keyword_id"]).limit(1).execute().data
    )
    if not submarket or not keyword:
        return _fail(db, report, "submarket or keyword no longer exists")
    submarket_row, keyword_row = submarket[0], keyword[0]
    report.submarket = str(submarket_row.get("name") or "")
    report.keyword = str(keyword_row.get("term") or "")

    market = (
        db.table("market").select("*").eq("id", submarket_row["market_id"]).limit(1).execute().data
    )
    if not market:
        return _fail(db, report, "market no longer exists")
    market_row = market[0]

    # Scan budget FIRST — before any money — so we never pay for discovery and then fail the scan
    # on budget. The ingest half has its own cost gate inside run_ingest (also against
    # max_market_run_cost_cents), which fires before its first paid call.
    from .geometry import point_count  # local import keeps module import cheap

    expected = point_count(
        float(submarket_row["grid_radius_miles"]), float(submarket_row["grid_spacing_miles"])
    )
    denial = budget_denial(
        estimate_cost_cents(expected, settings.dataforseo_cost_per_request_cents),
        settings.max_market_run_cost_cents,
    )
    if denial:
        return _fail(db, report, denial)

    # --- STAGE 1: discover (paid Outscraper pull; the business type is the category) -----------
    report.stage = "ingest"
    _update(db, report.order_id, {"stage": "ingest"})
    try:
        tiles = seeding.submarket_rows_to_tiling([submarket_row])
        ingest = await run_ingest(
            client=db,
            settings=settings,
            market_id=submarket_row["market_id"],
            market_name=str(market_row.get("name") or ""),
            categories=[order["category"]],
            submarkets=tiles,
            region=str(order.get("region") or ""),
        )
    except CostLimitExceeded as exc:
        # The ingest cost gate fired before spending — nothing was pulled, nothing scanned.
        return _fail(db, report, f"ingest refused before spending: {exc}")
    except Exception as exc:  # noqa: BLE001 — order must resolve; some tiles may have persisted
        logger.error("onboard ingest failed", extra={"order_id": report.order_id})
        return _fail(db, report, f"ingest failed: {repr(exc)[:400]}")
    report.prospects_ingested = int(getattr(ingest, "prospects_written", 0) or 0)

    # --- STAGE 2: filter (free) -----------------------------------------------------------------
    report.stage = "filter"
    _update(db, report.order_id, {"stage": "filter", "prospects_ingested": report.prospects_ingested})
    try:
        fr = run_filter(
            client=db,
            settings=settings,
            market_id=submarket_row["market_id"],
            # The typed business type IS the ingest category, so it keys the vertical's allow-list.
            accepted_categories=resolve_accepted_categories(
                str(order.get("category") or ""), settings.filter_category_relevance
            ),
            category_relevance_enabled=settings.filter_category_relevance_enabled,
            distance_gate_enabled=settings.filter_max_distance_enabled,
            max_distance_miles=settings.filter_max_distance_miles,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("onboard filter failed", extra={"order_id": report.order_id})
        return _fail(db, report, f"filter failed: {repr(exc)[:400]}")
    report.prospects_survived = int(getattr(fr, "survived", 0) or 0)

    # --- STAGE 3: scan (paid geogrid) -----------------------------------------------------------
    report.stage = "scan"
    _update(db, report.order_id, {"stage": "scan", "prospects_survived": report.prospects_survived})
    try:
        submitted = await scan_runner.submit_scan(db, settings, submarket_row, keyword_row)
    except Exception as exc:  # noqa: BLE001
        logger.error("onboard scan failed in submit", extra={"order_id": report.order_id})
        return _fail(db, report, f"scan failed: {repr(exc)[:400]}")

    report.snapshot_id = submitted.snapshot_id
    report.posted = submitted.posted
    report.problems = list(submitted.problems)

    if submitted.posted == 0:
        # cmd_scan's rule: posting nothing while believing a scan happened is the worst outcome;
        # keep the snapshot findable so whatever was spent is not orphaned behind a refusal.
        return _fail(
            db, report, "no tasks posted; see the snapshot's scan_task rows",
            snapshot_id=submitted.snapshot_id,
        )

    report.stage = "done"
    report.outcome = "done"
    _finish(
        db,
        report.order_id,
        {
            "status": "done",
            "stage": "done",
            "snapshot_id": submitted.snapshot_id,
            "prospects_ingested": report.prospects_ingested,
            "prospects_survived": report.prospects_survived,
            "error": None,
        },
    )
    logger.info(
        "onboard order executed",
        extra={
            "order_id": report.order_id,
            "snapshot_id": submitted.snapshot_id,
            "ingested": report.prospects_ingested,
            "survived": report.prospects_survived,
            "posted": submitted.posted,
        },
    )
    return report
