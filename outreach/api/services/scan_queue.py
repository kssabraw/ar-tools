"""The signed-order drain: how a UI click becomes a paid scan without touching the deploy path.

DECISIONS.md 2026-08-06. The `scan_request` table is the confirmation for UI-triggered runs the
way `OUTREACH_CONFIRM_SPEND` is for config-driven ones: evidence of deliberate human intent that
the accidental path cannot supply. This module consumes that evidence — it claims at most ONE
pending order, checks it against the budget gate, runs `submit_scan`, and records the outcome on
the order itself, terminally.

Deliberate narrownesses, each load-bearing:

- **One order per tick.** The drain is the UI-path descendant of the one-submarket ruling. A
  queue of five orders takes five ticks; that is a feature, because each scan's collection
  starts before the next scan's spend.
- **A failed order is terminal.** It is re-placed by a human who has read the error, never
  retried by the machine. Automatic retry is how one click becomes N paid scans — the exact
  shape of the duplicate-ingest incident (HANDOFF §6.4), rebuilt in miniature.
- **Claims are conditional.** `update .. where status = 'pending'` claims the row only if nobody
  else has; a claim that comes back empty means we lost the race and drain NOTHING this tick.
  There is one worker today (single service, cron skips overlapping runs), so the condition is
  cheap insurance rather than a concurrency design.
- **The budget gate runs before the money.** `max_market_run_cost_cents` never covered scans
  (ISSUES I-086); here it is checked against the order's estimated cost before anything posts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import scan_runner

logger = logging.getLogger(__name__)


@dataclass
class DrainReport:
    """What one tick's drain did. Everything the operator needs is on the ORDER ROW too —
    this is the log-line copy, not the durable copy (the I-087 lesson, applied forward)."""

    claimed: int = 0            # 0 or 1 by construction
    order_id: str = ""
    submarket: str = ""
    keyword: str = ""
    outcome: str = "idle"       # idle | done | failed
    snapshot_id: str = ""
    posted: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


def estimate_cost_cents(expected_points: int, per_request_cents: int) -> int:
    """What executing an order should cost: one queued task_post per grid point."""
    return max(0, expected_points) * max(0, per_request_cents)


def budget_denial(estimate_cents: int, max_run_cost_cents: int) -> str | None:
    """Why an order may NOT run, or None. Mirrors `spend_denial`'s shape: a refusal names the
    numbers so the person reading the failed order can decide, rather than re-derive."""
    if estimate_cents > max_run_cost_cents:
        return (
            f"estimated cost {estimate_cents}¢ exceeds max_market_run_cost_cents "
            f"{max_run_cost_cents}¢ — order refused before anything was posted"
        )
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending order, claimed, or None.

    Read-then-conditionally-claim. The claim re-checks `status = 'pending'`, so a row somebody
    else claimed between the read and the write comes back empty and we take nothing — losing a
    race costs a tick, winning it twice costs a paid scan.
    """
    rows = (
        db.table("scan_request")
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
        db.table("scan_request")
        .update({"status": "running", "started_at": _now()})
        .eq("id", order["id"])
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    return dict(order, status="running") if claimed else None


def _finish(db: Any, order_id: str, fields: dict[str, Any]) -> None:
    db.table("scan_request").update(dict(fields, finished_at=_now())).eq(
        "id", order_id
    ).execute()


async def drain_one(db: Any, settings: Settings) -> DrainReport:
    """Claim and execute at most one order. Never raises past recording the failure.

    Failure handling is asymmetric on purpose. Everything BEFORE `submit_scan` fails the order
    cleanly — nothing was spent, the refusal is the whole story. A failure DURING submission is
    recorded but the order still resolves from what actually happened: `submit_scan` writes
    `scan_task` rows before money moves, so a partial post has a snapshot and paid tasks that
    the collector will still rescue. Marking that order `failed` with its snapshot_id attached
    keeps the money findable instead of orphaning it behind a refusal message.
    """
    report = DrainReport()
    order = claim_next_order(db)
    if order is None:
        return report

    report.claimed = 1
    report.order_id = str(order["id"])

    submarket = (
        db.table("submarket").select("*").eq("id", order["submarket_id"]).limit(1).execute().data
    )
    keyword = (
        db.table("keyword").select("*").eq("id", order["keyword_id"]).limit(1).execute().data
    )
    if not submarket or not keyword:
        # An order referencing a vanished target. FKs make this near-impossible, but a refusal
        # here is free and the alternative is an exception that leaves the order stuck `running`.
        report.outcome = "failed"
        report.error = "submarket or keyword no longer exists"
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        return report

    report.submarket = str(submarket[0].get("name") or "")
    report.keyword = str(keyword[0].get("term") or "")

    from .geometry import point_count  # local import keeps module import cheap for tests

    expected = point_count(
        float(submarket[0]["grid_radius_miles"]), float(submarket[0]["grid_spacing_miles"])
    )
    estimate = estimate_cost_cents(expected, settings.dataforseo_cost_per_request_cents)
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial})
        return report

    try:
        submitted = await scan_runner.submit_scan(db, settings, submarket[0], keyword[0])
    except Exception as exc:  # noqa: BLE001 — the order must resolve; a stuck `running` row
        # blocks its (submarket, keyword) pair forever via the one-active index.
        report.outcome = "failed"
        report.error = repr(exc)[:500]
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        logger.error("scan order failed in submit", extra={"order_id": report.order_id})
        return report

    report.snapshot_id = submitted.snapshot_id
    report.posted = submitted.posted
    report.problems = list(submitted.problems)

    if submitted.posted == 0:
        # The cmd_scan reasoning verbatim: posting nothing while believing a scan happened is
        # the worst outcome available — the snapshot exists and finalizes complete-with-zero.
        report.outcome = "failed"
        report.error = "no tasks posted; see problems on the snapshot's scan_task rows"
        _finish(
            db,
            report.order_id,
            {"status": "failed", "error": report.error, "snapshot_id": submitted.snapshot_id},
        )
        return report

    report.outcome = "done"
    _finish(
        db,
        report.order_id,
        {"status": "done", "snapshot_id": submitted.snapshot_id, "error": None},
    )
    logger.info(
        "scan order executed",
        extra={
            "order_id": report.order_id,
            "snapshot_id": submitted.snapshot_id,
            "posted": submitted.posted,
        },
    )
    return report
