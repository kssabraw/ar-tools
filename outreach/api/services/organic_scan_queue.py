"""The signed-order drain for the report's ORGANIC signal: a UI click → one paid organic SERP.

The `organic_scan_request` table (migration 20260810140000) is the confirmation for a UI-triggered
organic capture, exactly as `scan_request` is for a geogrid scan: evidence of deliberate human
intent the accidental deploy path cannot supply. This module consumes that evidence — it claims at
most ONE pending order, budget-gates it, runs `organic_scan.capture_organic`, and records the
outcome on the order itself, terminally. It is the direct sibling of `scan_queue.drain_one`, and
its narrownesses are load-bearing for the same reasons documented there:

- **One order per tick.** A queue of five orders takes five ticks; each capture is billed and
  recorded before the next is claimed.
- **A failed order is terminal.** Re-placed by a human who read the error, never machine-retried.
- **Claims are conditional.** `update .. where status = 'pending'` — losing the race costs a tick,
  winning it twice costs a paid capture.
- **The budget gate runs before the money.** Checked against `max_market_run_cost_cents`.

Organic is idempotent per snapshot: a snapshot already carrying a `serp_result` drains as a free
`done` no-op (`capture_organic` returns `already_captured`), so a re-order — or a second prospect in
the same submarket — never re-bills.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import organic_scan

logger = logging.getLogger(__name__)


@dataclass
class OrganicDrainReport:
    """What one tick's organic drain did. Everything is also on the ORDER ROW — this is the
    log-line copy, not the durable copy."""

    claimed: int = 0            # 0 or 1 by construction
    order_id: str = ""
    snapshot_id: str = ""
    keyword: str = ""
    outcome: str = "idle"       # idle | done | failed
    already_captured: bool = False
    error: str = ""
    problems: list[str] = field(default_factory=list)


def estimate_cost_cents(per_request_cents: int) -> int:
    """What executing an organic order should cost: exactly one DataForSEO organic request."""
    return max(0, per_request_cents)


def budget_denial(estimate_cents: int, max_run_cost_cents: int) -> str | None:
    """Why an order may NOT run, or None. Mirrors `scan_queue.budget_denial`: a refusal names the
    numbers so the person reading the failed order can decide rather than re-derive."""
    if estimate_cents > max_run_cost_cents:
        return (
            f"estimated cost {estimate_cents}¢ exceeds max_market_run_cost_cents "
            f"{max_run_cost_cents}¢ — order refused before anything was posted"
        )
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Auto-enqueue: the paid-placement / organic signal runs on EVERY scan (owner ruling 2026-08-27),
# not only on a UI click. An auto order carries a machine note + a sentinel requester so it stays
# auditable apart from a deliberate click.
_AUTO_NOTE = "auto: organic + paid-placement signal on scan completion"


def enqueue_for_snapshot(db: Any, settings: Settings, snapshot_id: str) -> bool:
    """Auto-place a signed organic order for a just-finalized snapshot so the ORGANIC / paid-placement
    signal is captured on every scan (owner ruling 2026-08-27), rather than only when someone clicks.
    Returns True iff a NEW order was placed.

    Gated on `organic_auto_enabled`. **Idempotent** — skips if this snapshot already has ANY organic
    order (`finalize_snapshot` can be reached again on a later tick's stale-recovery, and a re-touch
    must never re-bill) or already carries a captured `google_organic` `serp_result`. **Best-effort**
    — never raises; a failed enqueue just means no auto-organic for that snapshot, still recoverable
    by the UI click. The order is the spend confirmation as always; here the STANDING confirmation is
    the config flag (the deliberate owner decision), and the sentinel `requested_by` marks it
    machine-originated. The drain still budget-gates and the capture is per-snapshot idempotent, so
    cost stays at most one organic SERP call per snapshot.
    """
    if not settings.organic_auto_enabled:
        return False
    try:
        snap = (
            db.table("scan_snapshot").select("id, keyword_id")
            .eq("id", snapshot_id).limit(1).execute().data or []
        )
        if not snap or not snap[0].get("keyword_id"):
            return False
        keyword_id = snap[0]["keyword_id"]

        # Idempotency 1: any prior order for this snapshot (any status) → already handled.
        if (
            db.table("organic_scan_request").select("id")
            .eq("snapshot_id", snapshot_id).limit(1).execute().data or []
        ):
            return False
        # Idempotency 2: the snapshot already carries a captured organic SERP → nothing to do.
        if (
            db.table("serp_result").select("id")
            .eq("snapshot_id", snapshot_id).eq("engine", organic_scan.ENGINE)
            .limit(1).execute().data or []
        ):
            return False

        db.table("organic_scan_request").insert({
            "snapshot_id": snapshot_id,
            "keyword_id": keyword_id,
            "requested_by": settings.organic_auto_actor_id,
            "note": _AUTO_NOTE,
        }).execute()
        logger.info("auto-enqueued organic order", extra={"snapshot_id": snapshot_id})
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort; the one-active index also rejects a race
        logger.warning("auto organic enqueue skipped",
                       extra={"snapshot_id": snapshot_id, "error": str(exc)[:200]})
        return False


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending order, claimed, or None. Read-then-conditionally-claim, so a row somebody
    else claimed between the read and the write comes back empty and we take nothing."""
    rows = (
        db.table("organic_scan_request")
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
        db.table("organic_scan_request")
        .update({"status": "running", "started_at": _now()})
        .eq("id", order["id"])
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    return dict(order, status="running") if claimed else None


def _finish(db: Any, order_id: str, fields: dict[str, Any]) -> None:
    db.table("organic_scan_request").update(dict(fields, finished_at=_now())).eq(
        "id", order_id
    ).execute()


async def drain_one(db: Any, settings: Settings) -> OrganicDrainReport:
    """Claim and execute at most one organic order. Never raises past recording the failure."""
    report = OrganicDrainReport()
    order = claim_next_order(db)
    if order is None:
        return report

    report.claimed = 1
    report.order_id = str(order["id"])

    snapshot_rows = (
        db.table("scan_snapshot")
        .select("id, submarket_id, center_lat, center_lng, scanned_at, keyword_id")
        .eq("id", order["snapshot_id"])
        .limit(1)
        .execute()
        .data
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

    if snapshot.get("center_lat") is None or snapshot.get("center_lng") is None:
        report.outcome = "failed"
        report.error = "snapshot has no recorded centre — cannot anchor the organic SERP"
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        return report

    estimate = estimate_cost_cents(settings.dataforseo_cost_per_request_cents)
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial})
        return report

    # market_id for the cost_ledger row: snapshot → submarket → market. Best-effort — a missing
    # market_id only unlabels the ledger row, it must never fail the capture.
    market_id: str | None = None
    submarket_id = snapshot.get("submarket_id")
    if submarket_id:
        sub = (
            db.table("submarket").select("market_id").eq("id", submarket_id).limit(1).execute().data
        )
        if sub:
            market_id = sub[0].get("market_id")

    try:
        result = await organic_scan.capture_organic(
            db, settings, snapshot, keyword_term, market_id=market_id
        )
    except Exception as exc:  # noqa: BLE001 — the order must resolve; a stuck `running` row blocks
        # its (snapshot, keyword) pair forever via the one-active index.
        report.outcome = "failed"
        report.error = repr(exc)[:500]
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        logger.error("organic order failed in capture", extra={"order_id": report.order_id})
        return report

    report.already_captured = bool(result.already_captured)
    report.problems = list(result.problems)

    if not (result.stored or result.already_captured):
        report.outcome = "failed"
        detail = "; ".join(result.problems) or "no result returned"
        report.error = f"organic capture stored nothing: {detail}"
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        return report

    report.outcome = "done"
    _finish(db, report.order_id, {"status": "done", "error": None})
    logger.info(
        "organic order executed",
        extra={
            "order_id": report.order_id,
            "snapshot_id": report.snapshot_id,
            "already_captured": report.already_captured,
        },
    )
    return report
