"""The signed-order drain for the report's AI-VISIBILITY signal: a UI click → one paid AI scan.

The `ai_scan_request` table (migration 20260810140000) is the confirmation for a UI-triggered AI
capture, exactly as `scan_request` is for a geogrid scan. This module consumes it — it claims at
most ONE pending order, budget-gates it, runs `ai_visibility.run_ai_scan` (ChatGPT + Google AI
Overview for the ordered ai_region × keyword), and records the outcome on the order terminally.

Sibling of `organic_scan_queue.drain_one` / `scan_queue.drain_one`; the same narrownesses apply
(one order per tick, terminal failures, conditional claims, budget-before-money). Unlike organic,
`run_ai_scan` is best-effort PER ENGINE — a failed engine is stored as `present=False` with its
error rather than raising — so the order succeeds when at least one engine stored a row, and fails
(with the per-engine problems) only when nothing stored at all. That distinction matters: a stored
`present=False` is a real, citable finding ("the AI returned no usable answer"), while a total
store failure is an outage that must not be recorded as "the AI doesn't know this business".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from . import ai_visibility

logger = logging.getLogger(__name__)


@dataclass
class AiDrainReport:
    """What one tick's AI drain did. Everything is also on the ORDER ROW — this is the log copy."""

    claimed: int = 0            # 0 or 1 by construction
    order_id: str = ""
    ai_region: str = ""
    keyword: str = ""
    outcome: str = "idle"       # idle | done | failed
    stored: int = 0
    error: str = ""
    problems: list[str] = field(default_factory=list)


def estimate_cost_cents(openai_cents: int, per_request_cents: int) -> int:
    """What executing an AI order should cost: one OpenAI ChatGPT call + one DataForSEO AIO request."""
    return max(0, openai_cents) + max(0, per_request_cents)


def budget_denial(estimate_cents: int, max_run_cost_cents: int) -> str | None:
    """Why an order may NOT run, or None. Mirrors the other drains' shape."""
    if estimate_cents > max_run_cost_cents:
        return (
            f"estimated cost {estimate_cents}¢ exceeds max_market_run_cost_cents "
            f"{max_run_cost_cents}¢ — order refused before anything was posted"
        )
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def claim_next_order(db: Any) -> dict[str, Any] | None:
    """The oldest pending order, claimed, or None. Read-then-conditionally-claim."""
    rows = (
        db.table("ai_scan_request")
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
        db.table("ai_scan_request")
        .update({"status": "running", "started_at": _now()})
        .eq("id", order["id"])
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    return dict(order, status="running") if claimed else None


def _finish(db: Any, order_id: str, fields: dict[str, Any]) -> None:
    db.table("ai_scan_request").update(dict(fields, finished_at=_now())).eq(
        "id", order_id
    ).execute()


async def drain_one(db: Any, settings: Settings) -> AiDrainReport:
    """Claim and execute at most one AI order. Never raises past recording the failure."""
    report = AiDrainReport()
    order = claim_next_order(db)
    if order is None:
        return report

    report.claimed = 1
    report.order_id = str(order["id"])

    region_rows = (
        db.table("ai_region")
        .select("id, name, name_level, market_id")
        .eq("id", order["ai_region_id"])
        .limit(1)
        .execute()
        .data
    )
    keyword_rows = (
        db.table("keyword").select("id, term").eq("id", order["keyword_id"]).limit(1).execute().data
    )
    if not region_rows or not keyword_rows:
        report.outcome = "failed"
        report.error = "ai_region or keyword no longer exists"
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        return report

    ai_region = region_rows[0]
    keyword = keyword_rows[0]
    report.ai_region = str(ai_region.get("name") or "")
    report.keyword = str(keyword.get("term") or "")

    estimate = estimate_cost_cents(
        settings.ai_visibility_openai_cost_cents, settings.dataforseo_cost_per_request_cents
    )
    denial = budget_denial(estimate, settings.max_market_run_cost_cents)
    if denial:
        report.outcome = "failed"
        report.error = denial
        _finish(db, report.order_id, {"status": "failed", "error": denial})
        return report

    try:
        result = await ai_visibility.run_ai_scan(
            db, settings, ai_region, keyword, market_id=ai_region.get("market_id")
        )
    except Exception as exc:  # noqa: BLE001 — the order must resolve; a stuck `running` row blocks
        # its (ai_region, keyword) pair forever via the one-active index.
        report.outcome = "failed"
        report.error = repr(exc)[:500]
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        logger.error("ai order failed in scan", extra={"order_id": report.order_id})
        return report

    report.stored = int(result.stored)
    report.problems = list(result.problems)

    if result.stored <= 0:
        # Nothing stored at all — an outage, not "the AI doesn't know you". Record it as failed with
        # the per-engine problems so a human re-places it after reading why.
        report.outcome = "failed"
        detail = "; ".join(result.problems) or "no engine returned a usable answer"
        report.error = f"ai scan stored nothing: {detail}"
        _finish(db, report.order_id, {"status": "failed", "error": report.error})
        return report

    report.outcome = "done"
    _finish(db, report.order_id, {"status": "done", "error": None})
    logger.info(
        "ai order executed",
        extra={"order_id": report.order_id, "region": report.ai_region, "stored": report.stored},
    )
    return report
